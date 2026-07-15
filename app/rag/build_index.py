import json
from pathlib import Path

import faiss
import google.generativeai as genai
import numpy as np

from app.config import settings

RUNBOOK_DIR = Path(__file__).parent.parent.parent / "data" / "runbooks"
INDEX_DIR = Path(__file__).parent.parent.parent / "faiss_index"


def chunk_document(text: str, chunk_size: int = 500, overlap: int = 100) -> list[str]:
    words = text.split()
    chunks = []
    start = 0
    while start < len(words):
        end = start + chunk_size
        chunk = " ".join(words[start:end])
        chunks.append(chunk)
        start += chunk_size - overlap
    return chunks


def embed_texts(texts: list[str]) -> np.ndarray:
    genai.configure(api_key=settings.gemini_api_key)
    result = genai.embed_content(
        model="models/gemini-embedding-001",
        content=texts,
        task_type="retrieval_document",
    )
    return np.array(result["embedding"], dtype="float32")


def build_index():
    all_chunks = []
    chunk_metadata = []

    for md_file in sorted(RUNBOOK_DIR.glob("*.md")):
        text = md_file.read_text(encoding="utf-8")
        chunks = chunk_document(text)
        for i, chunk in enumerate(chunks):
            all_chunks.append(chunk)
            chunk_metadata.append(
                {"source": md_file.name, "chunk_index": i, "text": chunk}
            )

    if not all_chunks:
        print("No runbook files found.")
        return

    embeddings = embed_texts(all_chunks)

    dimension = embeddings.shape[1]
    index = faiss.IndexFlatL2(dimension)
    index.add(embeddings)

    INDEX_DIR.mkdir(exist_ok=True)
    faiss.write_index(index, str(INDEX_DIR / "runbooks.index"))

    with open(INDEX_DIR / "metadata.json", "w") as f:
        json.dump(chunk_metadata, f, indent=2)

    print(f"Built index with {len(all_chunks)} chunks from {len(list(RUNBOOK_DIR.glob('*.md')))} runbooks")


if __name__ == "__main__":
    build_index()
