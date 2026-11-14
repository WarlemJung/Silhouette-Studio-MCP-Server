import sys
import tempfile
from pathlib import Path
import pytest

# Garante que o diretorio src/ do projeto esteja no sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from silhouette_mcp import server  # noqa: E402


@pytest.fixture
def fixtures_dir() -> Path:
    """Retorna o diretorio de fixtures estaticas dos testes."""
    return Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(autouse=True)
def isolated_output_dir(monkeypatch):
    """Isola OUTPUT_DIR em uma pasta temporaria durante a execucao dos testes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        monkeypatch.setattr(server, "OUTPUT_DIR", tmp_path)
        yield tmp_path
