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

    with patch("httpx.get", side_effect=mock_get):
        docs = scrape_harvard_documents()
    assert docs == []


def test_scrape_harvard_documents_skips_short_content():
    from scripts.excercise_diet_reco.build_corpus import scrape_harvard_documents

    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.text = "<html><body><article>short</article></body></html>"

    with patch("httpx.get", return_value=mock_response):
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
