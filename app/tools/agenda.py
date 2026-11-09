"""Tool do coordenador para persistir compromissos no PostgreSQL."""

import os
from datetime import date
from typing import Any, Type

import psycopg
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from app.compromisso import FORMATO_DATA, FORMATO_HORARIO, hoje


DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://agenda_app:agenda_dev_password@localhost:5432/agenda",
)

SCHEMA = """
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


class AgendaToolInput(BaseModel):
    """Argumentos aceitos pela tool de agenda."""

    acao: str = Field(
        description="Uma das ações: criar, consultar, alterar ou deletar."
    )
    compromisso_id: int | None = Field(
        default=None,
        description="ID do compromisso, obrigatório para consultar, alterar ou deletar.",
    )
    tipo: str | None = None
    pessoa_idosa: str | None = None
    especialidade: str | None = None
    data: str | None = Field(default=None, description="Data no formato AAAA-MM-DD.")
    horario: str | None = Field(default=None, description="Horário no formato HH:MM.")
    local: str | None = None
    responsavel: str | None = None


class AgendaTool(BaseTool):
    """Executa operações seguras de agenda para o Agente 2."""

    name: str = "agenda"
    description: str = (
        "Consulta e altera compromissos no PostgreSQL. "
        "Use apenas para compromissos de cuidado já confirmados. "
        "Nunca invente valores ausentes."
    )
    args_schema: Type[BaseModel] = AgendaToolInput

    def _run(
        self,
        acao: str,
        compromisso_id: int | None = None,
        tipo: str | None = None,
        pessoa_idosa: str | None = None,
        especialidade: str | None = None,
        data: str | None = None,
        horario: str | None = None,
        local: str | None = None,
        responsavel: str | None = None,
    ) -> str:
        try:
            if acao == "criar":
                return self._criar(
                    tipo,
                    pessoa_idosa,
                    especialidade,
                    data,
                    horario,
                    local,
                    responsavel,
                )
            if acao == "consultar":
                return self._consultar(compromisso_id, data, pessoa_idosa)
            if acao == "alterar":
                return self._alterar(
                    compromisso_id,
                    tipo,
                    pessoa_idosa,
                    especialidade,
                    data,
                    horario,
                    local,
                    responsavel,
                )
            if acao == "deletar":
                return self._deletar(compromisso_id)
        except (psycopg.Error, ValueError) as erro:
            return f"Falha na operação da agenda: {erro}"

        return "Ação inválida. Use criar, consultar, alterar ou deletar."

    def _conectar(self) -> psycopg.Connection:
        connection = psycopg.connect(DATABASE_URL)
        connection.execute(SCHEMA)
        return connection

    def _validar_data_horario(self, data: str | None, horario: str | None) -> None:
        if data is not None:
            if not FORMATO_DATA.match(data):
                raise ValueError("data deve estar no formato AAAA-MM-DD")
            try:
                data_obj = date.fromisoformat(data)
            except ValueError as erro:
                raise ValueError("data inexistente no calendário") from erro
            if data_obj < hoje():
                raise ValueError("não é permitido usar uma data passada")

        if horario is not None and not FORMATO_HORARIO.match(horario):
            raise ValueError("horário deve estar no formato HH:MM")

    def _criar(
        self,
        tipo: str | None,
        pessoa_idosa: str | None,
        especialidade: str | None,
        data: str | None,
        horario: str | None,
        local: str | None,
        responsavel: str | None,
    ) -> str:
        obrigatorios = {
            "tipo": tipo,
            "pessoa_idosa": pessoa_idosa,
            "data": data,
            "horario": horario,
        }
        ausentes = [nome for nome, valor in obrigatorios.items() if not valor]
        if ausentes:
            raise ValueError("campos obrigatórios ausentes: " + ", ".join(ausentes))
        self._validar_data_horario(data, horario)

        with self._conectar() as connection:
            existente = connection.execute(
                """
                SELECT id FROM compromissos
                WHERE status = 'ativo' AND tipo = %s
                  AND pessoa_idosa = %s AND data = %s AND horario = %s
                LIMIT 1
                """,
                (tipo, pessoa_idosa, data, horario),
            ).fetchone()
            if existente:
                return f"Compromisso ativo já existe com id {existente[0]}."

            linha = connection.execute(
                """
                INSERT INTO compromissos
                    (tipo, pessoa_idosa, especialidade, data, horario, local,
                     responsavel)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id, tipo, pessoa_idosa, data, horario, status
                """,
                (
                    tipo,
                    pessoa_idosa,
                    especialidade,
                    data,
                    horario,
                    local,
                    responsavel,
                ),
            ).fetchone()
        return f"Compromisso criado: {_formatar_linha(linha)}"

    def _consultar(
        self,
        compromisso_id: int | None,
        data: str | None,
        pessoa_idosa: str | None,
    ) -> str:
        self._validar_data_horario(data, None)
        filtros: list[str] = ["status = 'ativo'"]
        valores: list[Any] = []
        if compromisso_id is not None:
            filtros.append("id = %s")
            valores.append(compromisso_id)
        if data is not None:
            filtros.append("data = %s")
            valores.append(data)
        if pessoa_idosa is not None:
            filtros.append("pessoa_idosa = %s")
            valores.append(pessoa_idosa)

        with self._conectar() as connection:
            linhas = connection.execute(
                f"""
                SELECT id, tipo, pessoa_idosa, especialidade, data, horario,
                       local, responsavel, status
                FROM compromissos
                WHERE {' AND '.join(filtros)}
                ORDER BY data, horario, id
                """,
                valores,
            ).fetchall()
        if not linhas:
            return "Nenhum compromisso ativo encontrado."
        return "Compromissos encontrados:\n" + "\n".join(
            _formatar_linha(linha) for linha in linhas
        )

    def _alterar(
        self,
        compromisso_id: int | None,
        tipo: str | None,
        pessoa_idosa: str | None,
        especialidade: str | None,
        data: str | None,
        horario: str | None,
        local: str | None,
        responsavel: str | None,
    ) -> str:
        if compromisso_id is None:
            raise ValueError("compromisso_id é obrigatório para alterar")
        obrigatorios = {
            "tipo": tipo,
            "pessoa_idosa": pessoa_idosa,
            "data": data,
            "horario": horario,
        }
        ausentes = [nome for nome, valor in obrigatorios.items() if not valor]
        if ausentes:
            raise ValueError("campos obrigatórios ausentes: " + ", ".join(ausentes))
        self._validar_data_horario(data, horario)

        with self._conectar() as connection:
            linha = connection.execute(
                """
                UPDATE compromissos
                SET tipo = %s, pessoa_idosa = %s, especialidade = %s,
                    data = %s, horario = %s, local = %s, responsavel = %s,
                    atualizado_em = CURRENT_TIMESTAMP
                WHERE id = %s AND status = 'ativo'
                RETURNING id, tipo, pessoa_idosa, data, horario, status
                """,
                (
                    tipo,
                    pessoa_idosa,
                    especialidade,
                    data,
                    horario,
                    local,
                    responsavel,
                    compromisso_id,
                ),
            ).fetchone()
        if linha is None:
            return f"Compromisso ativo não encontrado: id {compromisso_id}."
        return f"Compromisso alterado: {_formatar_linha(linha)}"

    def _deletar(self, compromisso_id: int | None) -> str:
        if compromisso_id is None:
            raise ValueError("compromisso_id é obrigatório para deletar")

        with self._conectar() as connection:
            linha = connection.execute(
                """
                UPDATE compromissos
                SET status = 'cancelado', atualizado_em = CURRENT_TIMESTAMP
                WHERE id = %s AND status = 'ativo'
                RETURNING id, tipo, pessoa_idosa, data, horario, status
                """,
                (compromisso_id,),
            ).fetchone()
        if linha is None:
            return f"Compromisso ativo não encontrado: id {compromisso_id}."
        return f"Compromisso deletado: {_formatar_linha(linha)}"


def _formatar_linha(linha: tuple[Any, ...]) -> str:
    return ", ".join(str(valor) for valor in linha)
