import pytest
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_pdf_path():
    return FIXTURES_DIR / "sample.pdf"


@pytest.fixture
def sample_pdf_bytes(sample_pdf_path):
    return sample_pdf_path.read_bytes()


@pytest.fixture
def no_match_pdf_path():
    return FIXTURES_DIR / "no-match.pdf"


@pytest.fixture
def multi_match_pdf_path():
    return FIXTURES_DIR / "multi-match.pdf"
