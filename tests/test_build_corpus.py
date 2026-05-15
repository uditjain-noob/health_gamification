import pytest
from pathlib import Path

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
