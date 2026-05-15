import json
import types
import pytest
import apps.rag_retriever as rag
from unittest.mock import MagicMock, patch


def _make_doc(content: str, meta: dict):
    """Minimal stand-in for haystack.dataclasses.Document used in mocked retriever results."""
    return types.SimpleNamespace(content=content, meta=meta)


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


def test_retrieve_returns_content_from_store():
    """Verify retrieve() calls embedder + retriever and returns doc content."""
    mock_doc = _make_doc(
        content="Eat leafy greens to reduce liver inflammation.",
        meta={"organ": "liver", "category": "diet", "source": "harvard"},
    )

    mock_store = MagicMock()
    mock_retriever = MagicMock()
    mock_embedder = MagicMock()

    mock_embedder.run.return_value = {"embedding": [0.1] * 384}
    mock_retriever.run.return_value = {"documents": [mock_doc]}

    rag._store = mock_store
    rag._retriever = mock_retriever
    rag._text_embedder = mock_embedder

    result = rag.retrieve("liver diet", organ="liver")

    assert result == ["Eat leafy greens to reduce liver inflammation."]
    mock_embedder.run.assert_called_once_with(text="liver diet")


def test_retrieve_filters_by_category():
    """Verify retrieve() post-filters by category when category != 'all'."""
    diet_doc = _make_doc(
        content="Eat less fat.",
        meta={"organ": "heart", "category": "diet", "source": "harvard"},
    )
    exercise_doc = _make_doc(
        content="Walk 30 minutes daily.",
        meta={"organ": "heart", "category": "exercise", "source": "harvard"},
    )

    mock_store = MagicMock()
    mock_retriever = MagicMock()
    mock_embedder = MagicMock()

    mock_embedder.run.return_value = {"embedding": [0.1] * 384}
    mock_retriever.run.return_value = {"documents": [diet_doc, exercise_doc]}

    rag._store = mock_store
    rag._retriever = mock_retriever
    rag._text_embedder = mock_embedder

    result = rag.retrieve("heart health", organ="heart", category="diet")

    assert len(result) == 1
    assert result[0] == "Eat less fat."


def test_retrieve_respects_top_k():
    """Verify retrieve() returns at most top_k results."""
    docs = [
        _make_doc(content=f"Doc {i}", meta={"organ": "blood", "category": "diet"})
        for i in range(10)
    ]

    mock_store = MagicMock()
    mock_retriever = MagicMock()
    mock_embedder = MagicMock()

    mock_embedder.run.return_value = {"embedding": [0.1] * 384}
    mock_retriever.run.return_value = {"documents": docs}

    rag._store = mock_store
    rag._retriever = mock_retriever
    rag._text_embedder = mock_embedder

    result = rag.retrieve("blood iron", organ="blood", top_k=3)

    assert len(result) == 3


def test_fetch_rag_recommendations_returns_empty_when_no_context():
    from apps.recommendations import fetch_rag_recommendations
    mock_client = MagicMock()
    result = fetch_rag_recommendations(mock_client, organ="liver", query="elevated SGPT", context_chunks=[])
    assert result == {"diet": [], "exercise": [], "supplements": []}
    mock_client.complete.assert_not_called()


def test_fetch_rag_recommendations_calls_gemini_with_context():
    from apps.recommendations import fetch_rag_recommendations
    mock_client = MagicMock()
    mock_client.complete.return_value = json.dumps({
        "diet": [{"title": "Eat greens", "description": "Helps liver", "priority": "high"}],
        "exercise": [],
        "supplements": [],
    })
    result = fetch_rag_recommendations(
        mock_client,
        organ="liver",
        query="elevated SGPT liver",
        context_chunks=["Leafy greens reduce liver inflammation according to studies."],
    )
    assert result["diet"][0]["title"] == "Eat greens"
    mock_client.complete.assert_called_once()
    call_kwargs = mock_client.complete.call_args
    assert "Leafy greens" in call_kwargs.kwargs.get("user", "") or \
           "Leafy greens" in str(call_kwargs)


def test_fetch_rag_recommendations_raises_on_bad_json():
    from apps.recommendations import fetch_rag_recommendations
    mock_client = MagicMock()
    mock_client.complete.return_value = "not valid json"
    with pytest.raises(ValueError, match="invalid JSON"):
        fetch_rag_recommendations(
            mock_client,
            organ="liver",
            query="elevated SGPT",
            context_chunks=["some context here"],
        )
