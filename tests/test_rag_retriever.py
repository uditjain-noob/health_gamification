import pytest
import apps.rag_retriever as rag


def setup_function():
    rag._store = None
    rag._retriever = None
    rag._text_embedder = None


def test_retrieve_returns_empty_when_store_not_loaded():
    result = rag.retrieve("elevated SGPT liver diet", organ="liver")
    assert result == []


def test_load_store_missing_file_does_not_raise(tmp_path):
    rag.load_store(str(tmp_path / "nonexistent.json"))
    assert rag._store is None


def test_retrieve_returns_empty_after_missing_load(tmp_path):
    rag.load_store(str(tmp_path / "nonexistent.json"))
    result = rag.retrieve("cholesterol diet", organ="heart")
    assert result == []
