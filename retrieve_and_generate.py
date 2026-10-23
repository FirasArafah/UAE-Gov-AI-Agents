import pickle
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import faiss
import requests
from sentence_transformers import SentenceTransformer

CONFIG = {
    "embedding_model_name": "sentence-transformers/all-MiniLM-L6-v2",
    "index_dir": Path("data/index"),
    "ollama_url": "http://localhost:11434/api/generate",
    "ollama_model": "llama3.2",
    "top_k": 5,
    "temperature": 0.2,
}


def load_kb() -> Tuple[faiss.Index, List[Dict[str, Any]], SentenceTransformer]:
    index = faiss.read_index(str(CONFIG["index_dir"] / "faiss.index"))
    with open(CONFIG["index_dir"] / "metadata.pkl", "rb") as f:
        documents = pickle.load(f)
    embedder = SentenceTransformer(CONFIG["embedding_model_name"])
    print(f"Loaded KB: {index.ntotal} chunks")
    return index, documents, embedder


def retrieve(query, index, documents, embedder, top_k=5, kb_category=None):
    q = embedder.encode([query], normalize_embeddings=True).astype("float32")
    search_k = min(index.ntotal, top_k * 6) if kb_category else top_k
    scores, ids = index.search(q, search_k)

    results = []
    for score, idx in zip(scores[0], ids[0]):
        if idx == -1:
            continue
        item = documents[idx]
        if kb_category and item.get("kb_category") != kb_category:
            continue
        results.append({**item, "score": float(score)})
        if len(results) >= top_k:
            break
    return results


def build_prompt(query: str, contexts: List[Dict[str, Any]]) -> str:
    blocks = []
    for i, c in enumerate(contexts, 1):
        blocks.append(
            f"[{i}] Source: {c['source']} | Ref: {c['article_ref']} | "
            f"Page: {c['page']} | Category: {c['kb_category']}\n{c['text']}"
        )
    context_text = "\n\n".join(blocks)
    return f"""You are a UAE Government AI Policy & Legal Compliance Adviser.
Answer ONLY from the context below. Cite the source file, Article (or Page), and Page number for every claim.
If the answer is not in the context, say it was not found in the knowledge base.

Context:
{context_text}

Question: {query}

Answer:"""


def generate(prompt: str) -> str:
    r = requests.post(
        CONFIG["ollama_url"],
        json={
            "model": CONFIG["ollama_model"],
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": CONFIG["temperature"]},
        },
        timeout=300,
    )
    r.raise_for_status()
    return r.json()["response"].strip()


def ask(query: str, index, documents, embedder, kb_category=None) -> Dict[str, Any]:
    contexts = retrieve(query, index, documents, embedder,
                        top_k=CONFIG["top_k"], kb_category=kb_category)
    prompt = build_prompt(query, contexts)
    answer = generate(prompt)
    return {"query": query, "answer": answer, "contexts": contexts}


if __name__ == "__main__":
    index, documents, embedder = load_kb()

    question = "Can a person object to a decision made by an automated system on their residency application?"
    result = ask(question, index, documents, embedder, kb_category="uae_national")

    print("\nQUESTION:", result["query"])
    print("\nANSWER:\n", result["answer"])
    print("\nSOURCES:")
    for c in result["contexts"]:
        print(f"- {c['source']} | {c['article_ref']} | p.{c['page']} | score={c['score']:.4f}")