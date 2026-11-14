import sys
import tempfile
from pathlib import Path
import pytest

# Garante que o diretorio do servidor esta no sys.path
SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

import server

@pytest.fixture(autouse=True)
def isolated_output_dir(monkeypatch):
    """Isola OUTPUT_DIR em uma pasta temporaria durante a execucao dos testes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        monkeypatch.setattr(server, "OUTPUT_DIR", tmp_path)
        yield tmp_path

