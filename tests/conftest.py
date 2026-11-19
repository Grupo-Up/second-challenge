import sys
from pathlib import Path

import pytest

# Deixa `import app...` funcionar rodando `pytest` da raiz do projeto
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def banco_temporario(tmp_path, monkeypatch):
    """Cada teste com um SQLite novo, sem tocar no dados/agenda.sqlite."""
    from app.tools import banco

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(banco, "ARQUIVO", tmp_path / "teste.sqlite")
    return banco.ARQUIVO
