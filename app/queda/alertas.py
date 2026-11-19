"""Alertas de queda e o vinculo de cada relogio com um grupo da familia.

Duas tabelas, no mesmo banco da agenda (app/tools/banco.py):

    dispositivos  qual relogio pertence a qual pessoa idosa e a qual grupo
    alertas_queda cada alerta: probabilidade, versao do modelo, status e
                  o retorno da familia

Ciclo de um alerta:

    pendente -> enviado -> confirmado   (familia: "!queda ok")
                        -> falso        (familia: "!queda falso")

O status "falso" e o rotulo que alimenta o MLOps: cada alarme falso e
uma janela que o modelo errou e que vale a pena olhar no retreino.

O que NAO e gravado: o sinal do sensor. Do alerta fica so a
probabilidade e o horario (minimizacao, CLAUDE.md secao 8).
"""

from __future__ import annotations

from app.tools.banco import ajustar, conectar, usa_postgres

_SQLITE = [
    """
    CREATE TABLE IF NOT EXISTS dispositivos (
        dispositivo TEXT PRIMARY KEY,
        grupo TEXT NOT NULL,
        pessoa_idosa TEXT NOT NULL,
        criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS alertas_queda (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        dispositivo TEXT NOT NULL,
        grupo TEXT NOT NULL,
        pessoa_idosa TEXT NOT NULL,
        probabilidade REAL NOT NULL,
        versao_modelo TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pendente'
            CHECK (status IN ('pendente', 'enviado', 'confirmado', 'falso')),
        criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        atualizado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
]

_POSTGRES = [
    """
    CREATE TABLE IF NOT EXISTS dispositivos (
        dispositivo TEXT PRIMARY KEY,
        grupo TEXT NOT NULL,
        pessoa_idosa TEXT NOT NULL,
        criado_em TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS alertas_queda (
        id BIGSERIAL PRIMARY KEY,
        dispositivo TEXT NOT NULL,
        grupo TEXT NOT NULL,
        pessoa_idosa TEXT NOT NULL,
        probabilidade DOUBLE PRECISION NOT NULL,
        versao_modelo TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pendente'
            CHECK (status IN ('pendente', 'enviado', 'confirmado', 'falso')),
        criado_em TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
        atualizado_em TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
]

COLUNAS = ("id", "dispositivo", "grupo", "pessoa_idosa", "probabilidade", "versao_modelo", "status", "criado_em")


def _preparar(conexao) -> None:
    for comando in _POSTGRES if usa_postgres() else _SQLITE:
        conexao.execute(comando)


def _iso(valor) -> str:
    """Horario em ISO 8601 com fuso, para o bot converter sem ambiguidade.
    O SQLite devolve texto em UTC sem fuso; o Postgres devolve datetime."""
    if hasattr(valor, "isoformat"):
        return valor.isoformat()
    texto = str(valor).replace(" ", "T")
    return texto if texto.endswith("Z") or "+" in texto[10:] else texto + "Z"


def _como_dict(linha) -> dict:
    dados = dict(zip(COLUNAS, linha))
    dados["criado_em"] = _iso(dados["criado_em"])
    return dados


def vincular(dispositivo: str, grupo: str, pessoa_idosa: str) -> None:
    """Liga um relogio a um grupo. Refazer o vinculo troca o grupo."""
    with conectar() as conexao:
        _preparar(conexao)
        conexao.execute(ajustar("DELETE FROM dispositivos WHERE dispositivo = ?"), (dispositivo,))
        conexao.execute(
            ajustar("INSERT INTO dispositivos (dispositivo, grupo, pessoa_idosa) VALUES (?, ?, ?)"),
            (dispositivo, grupo, pessoa_idosa),
        )


def vinculo(dispositivo: str) -> dict | None:
    with conectar() as conexao:
        _preparar(conexao)
        linha = conexao.execute(
            ajustar("SELECT grupo, pessoa_idosa FROM dispositivos WHERE dispositivo = ?"),
            (dispositivo,),
        ).fetchone()
    return {"grupo": linha[0], "pessoa_idosa": linha[1]} if linha else None


def registrar(dispositivo: str, probabilidade: float, versao_modelo: str) -> dict | None:
    """Cria o alerta pendente. Sem vinculo, nao ha para quem avisar: None."""
    destino = vinculo(dispositivo)
    if destino is None:
        return None
    with conectar() as conexao:
        _preparar(conexao)
        linha = conexao.execute(
            ajustar(
                "INSERT INTO alertas_queda "
                "(dispositivo, grupo, pessoa_idosa, probabilidade, versao_modelo) "
                "VALUES (?, ?, ?, ?, ?) RETURNING " + ", ".join(COLUNAS)
            ),
            (dispositivo, destino["grupo"], destino["pessoa_idosa"], float(probabilidade), versao_modelo),
        ).fetchone()
    return _como_dict(linha)


def pendentes() -> list[dict]:
    with conectar() as conexao:
        _preparar(conexao)
        linhas = conexao.execute(
            "SELECT " + ", ".join(COLUNAS) + " FROM alertas_queda WHERE status = 'pendente' ORDER BY id"
        ).fetchall()
    return [_como_dict(linha) for linha in linhas]


def marcar_enviado(alerta_id: int) -> bool:
    with conectar() as conexao:
        _preparar(conexao)
        linha = conexao.execute(
            ajustar(
                "UPDATE alertas_queda SET status = 'enviado', atualizado_em = CURRENT_TIMESTAMP "
                "WHERE id = ? AND status = 'pendente' RETURNING id"
            ),
            (alerta_id,),
        ).fetchone()
    return linha is not None


def registrar_retorno(grupo: str, foi_queda: bool) -> dict | None:
    """Retorno da familia sobre o ULTIMO alerta enviado ao grupo."""
    novo = "confirmado" if foi_queda else "falso"
    with conectar() as conexao:
        _preparar(conexao)
        linha = conexao.execute(
            ajustar(
                "SELECT id FROM alertas_queda WHERE grupo = ? AND status = 'enviado' "
                "ORDER BY id DESC LIMIT 1"
            ),
            (grupo,),
        ).fetchone()
        if linha is None:
            return None
        atualizado = conexao.execute(
            ajustar(
                "UPDATE alertas_queda SET status = ?, atualizado_em = CURRENT_TIMESTAMP "
                "WHERE id = ? RETURNING " + ", ".join(COLUNAS)
            ),
            (novo, linha[0]),
        ).fetchone()
    return _como_dict(atualizado)


def resumo_retornos() -> dict:
    """Contagem por status: e a metrica de producao do detector."""
    with conectar() as conexao:
        _preparar(conexao)
        linhas = conexao.execute(
            "SELECT status, COUNT(*) FROM alertas_queda GROUP BY status"
        ).fetchall()
    contagem = {status: int(n) for status, n in linhas}
    confirmados, falsos = contagem.get("confirmado", 0), contagem.get("falso", 0)
    avaliados = confirmados + falsos
    return {
        **contagem,
        "precisao_em_producao": confirmados / avaliados if avaliados else None,
    }
