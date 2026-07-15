import asyncio
import hashlib
import json
import logging
import time
from typing import Optional, Type

import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted
from pydantic import BaseModel, ValidationError

from app.config import settings
from app.observability import (
    llm_calls_total,
    llm_errors_total,
    llm_latency_seconds,
    llm_rate_limit_backoffs_total,
    llm_tokens_total,
)

logger = logging.getLogger("sentinel")


def _setup_logging():
    log_dir = __import__("pathlib").Path("logs")
    log_dir.mkdir(exist_ok=True)
    handler = logging.FileHandler(log_dir / "sentinel.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(settings.log_level)


_setup_logging()

RATE_LIMIT_MAX_RETRIES = 4
RATE_LIMIT_BASE_DELAY = 20


async def _rate_limit_backoff(attempt: int, agent_name: str):
    delay = RATE_LIMIT_BASE_DELAY * (2 ** attempt)
    llm_rate_limit_backoffs_total.labels(agent=agent_name).inc()
    logger.info(json.dumps({
        "event": "rate_limit_backoff",
        "agent": agent_name,
        "attempt": attempt + 1,
        "delay_seconds": delay,
    }))
    print(f"  [rate limit] Waiting {delay}s before retry (attempt {attempt + 1})...")
    await asyncio.sleep(delay)


def _extract_token_usage(response) -> tuple[int, int]:
    """Read (prompt_tokens, completion_tokens) from a google.generativeai response.
    Returns (0, 0) if usage metadata is missing (SDK version drift or streaming)."""
    try:
        usage = getattr(response, "usage_metadata", None)
        if usage is None:
            return 0, 0
        prompt = getattr(usage, "prompt_token_count", 0) or 0
        completion = getattr(usage, "candidates_token_count", 0) or 0
        return int(prompt), int(completion)
    except Exception:
        return 0, 0


class LLMClient:
    def __init__(self):
        genai.configure(api_key=settings.gemini_api_key)
        self._models: dict[str, genai.GenerativeModel] = {}

    def _get_model(self, model_name: Optional[str] = None) -> genai.GenerativeModel:
        name = model_name or settings.gemini_model
        if name not in self._models:
            self._models[name] = genai.GenerativeModel(name)
        return self._models[name]

    async def call(
        self,
        agent_name: str,
        prompt: str,
        response_schema: Optional[Type[BaseModel]] = None,
        max_retries: int = 1,
        model: Optional[str] = None,
    ) -> dict:
        prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()[:12]
        start = time.time()

        log_entry = {
            "event": "llm_call_start",
            "agent": agent_name,
            "prompt_hash": prompt_hash,
            "model": model or settings.gemini_model,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        logger.info(json.dumps(log_entry))

        schema_instruction = ""
        if response_schema:
            fields = response_schema.model_json_schema()
            schema_instruction = (
                f"\n\nYou MUST respond with valid JSON matching this schema:\n"
                f"{json.dumps(fields, indent=2)}\n"
                f"Respond ONLY with the JSON object, no markdown fences or extra text."
            )

        full_prompt = prompt + schema_instruction
        last_error = None
        gen_model = self._get_model(model)
        active_model = model or settings.gemini_model

        for attempt in range(max_retries + 1):
            for rate_attempt in range(RATE_LIMIT_MAX_RETRIES):
                try:
                    retry_note = ""
                    if attempt > 0 and last_error:
                        retry_note = (
                            f"\n\nYour previous response failed validation: {last_error}\n"
                            f"Please fix the output and try again."
                        )

                    call_start = time.time()
                    response = gen_model.generate_content(full_prompt + retry_note)
                    call_latency = time.time() - call_start
                    llm_latency_seconds.labels(
                        agent=agent_name, model=active_model
                    ).observe(call_latency)

                    prompt_tokens, completion_tokens = _extract_token_usage(response)
                    if prompt_tokens:
                        llm_tokens_total.labels(
                            agent=agent_name, model=active_model, direction="prompt"
                        ).inc(prompt_tokens)
                    if completion_tokens:
                        llm_tokens_total.labels(
                            agent=agent_name, model=active_model, direction="completion"
                        ).inc(completion_tokens)

                    raw_text = response.text.strip()

                    if raw_text.startswith("```"):
                        lines = raw_text.split("\n")
                        lines = lines[1:] if lines[0].startswith("```") else lines
                        if lines and lines[-1].strip() == "```":
                            lines = lines[:-1]
                        raw_text = "\n".join(lines)

                    latency_ms = int((time.time() - start) * 1000)
                    log_entry = {
                        "event": "llm_call_end",
                        "agent": agent_name,
                        "prompt_hash": prompt_hash,
                        "model": active_model,
                        "latency_ms": latency_ms,
                        "attempt": attempt + 1,
                        "response_length": len(raw_text),
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                    }
                    logger.info(json.dumps(log_entry))

                    if response_schema:
                        parsed = json.loads(raw_text)
                        validated = response_schema.model_validate(parsed)
                        llm_calls_total.labels(
                            agent=agent_name, model=active_model, outcome="success"
                        ).inc()
                        return validated.model_dump()

                    llm_calls_total.labels(
                        agent=agent_name, model=active_model, outcome="success"
                    ).inc()
                    return {"text": raw_text}

                except ResourceExhausted:
                    if rate_attempt < RATE_LIMIT_MAX_RETRIES - 1:
                        await _rate_limit_backoff(rate_attempt, agent_name)
                        continue
                    llm_errors_total.labels(
                        agent=agent_name, error_type="rate_limit_exhausted"
                    ).inc()
                    llm_calls_total.labels(
                        agent=agent_name, model=active_model, outcome="error"
                    ).inc()
                    raise

                except (json.JSONDecodeError, ValidationError) as e:
                    last_error = str(e)
                    if attempt == max_retries:
                        llm_calls_total.labels(
                            agent=agent_name, model=active_model, outcome="validation_failure"
                        ).inc()
                        llm_errors_total.labels(
                            agent=agent_name, error_type="validation"
                        ).inc()
                        logger.error(
                            json.dumps({
                                "event": "llm_validation_failed",
                                "agent": agent_name,
                                "error": last_error,
                            })
                        )
                        raise ValueError(
                            f"LLM output validation failed for {agent_name} after "
                            f"{max_retries + 1} attempts: {last_error}"
                        )
                    break

                except Exception as e:
                    llm_errors_total.labels(
                        agent=agent_name, error_type=type(e).__name__
                    ).inc()
                    llm_calls_total.labels(
                        agent=agent_name, model=active_model, outcome="error"
                    ).inc()
                    logger.error(
                        json.dumps({
                            "event": "llm_call_error",
                            "agent": agent_name,
                            "error": str(e),
                        })
                    )
                    raise

        raise ValueError(f"LLM call exhausted all retries for {agent_name}")


llm_client = LLMClient()
