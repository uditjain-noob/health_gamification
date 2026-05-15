import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

PDF_PATH = "scripts/excercise_diet_reco/biomarkers_excercise/biomarkers.pdf"


@pytest.mark.skipif(not Path(PDF_PATH).exists(), reason="NSCA PDF not present")
def test_extract_nsca_documents_returns_seven_sections():
    from scripts.excercise_diet_reco.build_corpus import extract_nsca_documents
    docs = extract_nsca_documents(PDF_PATH)
    assert len(docs) == 7


@pytest.mark.skipif(not Path(PDF_PATH).exists(), reason="NSCA PDF not present")
def test_extract_nsca_documents_meta_schema():
    from scripts.excercise_diet_reco.build_corpus import extract_nsca_documents
    docs = extract_nsca_documents(PDF_PATH)
    for doc in docs:
        assert doc.meta["source"] == "nsca"
        assert "organ" in doc.meta
        assert "category" in doc.meta
        assert "parameters" in doc.meta
        assert isinstance(doc.meta["parameters"], list)
        assert len(doc.content) > 100


def test_scrape_harvard_documents_skips_http_errors():
    import httpx
    from scripts.excercise_diet_reco.build_corpus import scrape_harvard_documents

    def mock_get(url, **kwargs):
        raise httpx.HTTPError("connection refused")

    # Patch both cache and HTTP so neither provides content
    with patch("httpx.get", side_effect=mock_get), \
         patch("scripts.excercise_diet_reco.build_corpus._load_cached_page", return_value=None):
        docs = scrape_harvard_documents()
    assert docs == []


def test_scrape_harvard_documents_skips_short_content():
    from scripts.excercise_diet_reco.build_corpus import scrape_harvard_documents

    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.text = "<html><body><article>short</article></body></html>"

    # Patch both cache (returns None) and HTTP (returns short content)
    with patch("httpx.get", return_value=mock_response), \
         patch("scripts.excercise_diet_reco.build_corpus._load_cached_page", return_value=None):
        docs = scrape_harvard_documents()
    assert docs == []


def test_scrape_harvard_documents_meta_schema():
    from scripts.excercise_diet_reco.build_corpus import scrape_harvard_documents

    long_text = "This is a sentence. " * 30
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.text = f"<html><body><article>{long_text}</article></body></html>"

    with patch("httpx.get", return_value=mock_response):
        with patch("time.sleep"):  # don't actually sleep during tests
            docs = scrape_harvard_documents()

    assert len(docs) > 0
    for doc in docs:
        assert doc.meta["source"] == "harvard"
        assert "organ" in doc.meta
        assert "category" in doc.meta
        assert isinstance(doc.meta["parameters"], list)


def test_chunk_harvard_documents_inherits_meta():
    from scripts.excercise_diet_reco.build_corpus import chunk_harvard_documents
    from haystack import Document

    docs = [Document(
        content=(
            "Eating fiber reduces cholesterol. "
            "Soluble fiber binds bile acids. "
            "This lowers LDL levels significantly. "
            "Oats and beans are excellent sources. "
            "Aim for 25 grams daily. "
            "Insoluble fiber aids digestion. "
            "Both types improve metabolic health."
        ),
        meta={
            "source": "harvard",
            "organ": "heart",
            "category": "diet",
            "condition": "high LDL",
            "parameters": ["LDL"],
            "url": "http://example.com",
        },
    )]
    chunks = chunk_harvard_documents(docs)
    assert len(chunks) >= 1
    assert all(c.meta["organ"] == "heart" for c in chunks)
    assert all(c.meta["source"] == "harvard" for c in chunks)


def test_build_dry_run_prints_counts(capsys):
    from scripts.excercise_diet_reco.build_corpus import build
    from haystack import Document

    dummy_doc = Document(
        content="Sentence one. Sentence two. Sentence three. Sentence four. Sentence five. Sentence six.",
        meta={"source": "harvard", "organ": "heart", "category": "diet",
              "condition": "", "parameters": [], "url": "http://x.com"},
    )

    with patch("scripts.excercise_diet_reco.build_corpus.scrape_harvard_documents", return_value=[dummy_doc]):
        with patch("scripts.excercise_diet_reco.build_corpus.extract_nsca_documents", return_value=[]):
            build(dry_run=True, pdf_path="scripts/excercise_diet_reco/biomarkers_excercise/biomarkers.pdf")

    captured = capsys.readouterr()
    assert "chunk" in captured.out.lower() or "total" in captured.out.lower()
