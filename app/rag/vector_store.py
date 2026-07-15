import json
from pathlib import Path
from typing import Optional

import faiss
import google.generativeai as genai
import numpy as np

from app.config import settings

INDEX_DIR = Path(__file__).parent.parent.parent / "faiss_index"


def _embed_query(text: str) -> np.ndarray:
    genai.configure(api_key=settings.gemini_api_key)
    result = genai.embed_content(
        model="models/gemini-embedding-001",
        content=text,
        task_type="retrieval_query",
    )
    return np.array([result["embedding"]], dtype="float32")


class VectorStore:
    def __init__(self):
        self._index: Optional[faiss.Index] = None
        self._metadata: Optional[list[dict]] = None

    def _ensure_loaded(self):
        if self._index is None:
            index_path = INDEX_DIR / "runbooks.index"
            meta_path = INDEX_DIR / "metadata.json"
            if not index_path.exists():
                from app.rag.build_index import build_index
                build_index()
            self._index = faiss.read_index(str(index_path))
            with open(meta_path) as f:
                self._metadata = json.load(f)

    def retrieve(self, query: str, top_k: int = 3) -> list[dict]:
        self._ensure_loaded()
        query_embedding = _embed_query(query)
        distances, indices = self._index.search(query_embedding, top_k)

        results = []
        for i, idx in enumerate(indices[0]):
            if idx < len(self._metadata):
                result = self._metadata[idx].copy()
                result["score"] = float(distances[0][i])
                results.append(result)
        return results

    def rebuild_index(self):
        from app.rag.build_index import build_index
        build_index()
        self._index = None
        self._metadata = None
        self._ensure_loaded()


vector_store = VectorStore()


def retrieve_sop(query: str) -> str:
    results = vector_store.retrieve(query, top_k=3)
    if not results:
        return "No relevant SOP/runbook entries found."
    context_parts = []
    for r in results:
        context_parts.append(f"[From {r['source']}]:\n{r['text']}")
    return "\n\n---\n\n".join(context_parts)
