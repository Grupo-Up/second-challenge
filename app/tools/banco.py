
"""Onde os compromissos sao gravados.

Dois bancos, escolhidos pela DATABASE_URL:

    postgresql://...  ->  psycopg, o container do compose.yml
    nao definida      ->  SQLite em dados/agenda.sqlite

O time usa os dois: quem roda o Docker nao troca de banco, quem nao roda
nao instala nada. Este e o unico arquivo que sabe que ha dois.
"""

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

ARQUIVO = Path(__file__).resolve().parents[2] / "dados" / "agenda.sqlite"

SCHEMA_POSTGRES = """
CREATE TABLE IF NOT EXISTS compromissos (
    id BIGSERIAL PRIMARY KEY,
    tipo TEXT NOT NULL,
    pessoa_idosa TEXT NOT NULL,
    especialidade TEXT,
    data DATE NOT NULL,
    horario TIME NOT NULL,
    local TEXT,
    responsavel TEXT,
    status TEXT NOT NULL DEFAULT 'ativo'
        CHECK (status IN ('ativo', 'cancelado')),
    criado_em TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

# O SQLite nao tem DATE nem TIME, guarda texto. Como o projeto ja usa
# AAAA-MM-DD e HH:MM, ordenar como texto da a ordem cronologica.
SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS compromissos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo TEXT NOT NULL,
    pessoa_idosa TEXT NOT NULL,
    especialidade TEXT,
    data TEXT NOT NULL,
    horario TEXT NOT NULL,
    local TEXT,
    responsavel TEXT,
    status TEXT NOT NULL DEFAULT 'ativo'
        CHECK (status IN ('ativo', 'cancelado')),
    criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def usa_postgres() -> bool:
    """Lido a cada chamada, nao na importacao: assim da para trocar de
    banco num teste sem reimportar o modulo."""
    return (os.environ.get("DATABASE_URL") or "").startswith("postgresql")


def ajustar(sql: str) -> str:
    """O SQL e escrito com `?`; o psycopg usa `%s`."""
    return sql.replace("?", "%s") if usa_postgres() else sql


@contextmanager
def conectar():
    """Abre a conexao, cria a tabela se faltar, commita e fecha.

    Desfaz tudo se houver excecao: a tool nunca deve deixar meia escrita.
    """
    if usa_postgres():
        import psycopg

        conexao = psycopg.connect(os.environ["DATABASE_URL"])
        esquema = SCHEMA_POSTGRES
    else:
        ARQUIVO.parent.mkdir(parents=True, exist_ok=True)
        conexao = sqlite3.connect(str(ARQUIVO))
        esquema = SCHEMA_SQLITE

    try:
        conexao.execute(esquema)
        yield conexao
        conexao.commit()
    except Exception:
        conexao.rollback()
        raise
    finally:
        conexao.close()
