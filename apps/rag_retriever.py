from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger("healthquest.rag")

_store: Any = None
_retriever: Any = None
_text_embedder: Any = None

_DEFAULT_STORE_PATH = "scripts/excercise_diet_reco/corpus/store.json"


def load_store(path: str = _DEFAULT_STORE_PATH) -> None:
    global _store, _retriever, _text_embedder
    p = Path(path)
    if not p.exists():
        log.warning("RAG store not found at %s — get_rag_recommendations will return empty results", path)
        return
    try:
        from haystack.document_stores.in_memory import InMemoryDocumentStore
        from haystack.components.retrievers.in_memory import InMemoryEmbeddingRetriever
        from haystack.components.embedders import SentenceTransformersTextEmbedder

        data = json.loads(p.read_text())
        _store = InMemoryDocumentStore.from_dict(data)
        _retriever = InMemoryEmbeddingRetriever(document_store=_store)
        _text_embedder = SentenceTransformersTextEmbedder(model="BAAI/bge-small-en-v1.5")
        _text_embedder.warm_up()
        log.info("RAG store loaded: %d documents", _store.count_documents())
    except Exception as e:
        log.error("Failed to load RAG store: %s", e)
        _store = None
        _retriever = None
        _text_embedder = None


def retrieve(query: str, organ: str, category: str = "all", top_k: int = 5) -> list[str]:
    if _store is None or _retriever is None or _text_embedder is None:
        return []

    filters: dict = {
        "operator": "OR",
        "conditions": [
            {"field": "meta.organ", "operator": "==", "value": organ},
            {"field": "meta.organ", "operator": "==", "value": "all"},
        ],
    }

    result = _text_embedder.run(text=query)
    query_embedding = result["embedding"]

    docs = _retriever.run(
        query_embedding=query_embedding,
        filters=filters,
        top_k=top_k * 2,  # over-fetch before optional category post-filter
    )["documents"]

    if category != "all":
        docs = [d for d in docs if category in (d.meta.get("category") or "")]

    return [doc.content for doc in docs[:top_k]]
