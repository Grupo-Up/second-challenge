
"""Estrutura de um compromisso e as validacoes compartilhadas.

Usado pelos agentes para garantir que a saida da LLM tenha formato
verificavel. Campos desconhecidos ficam em None: nao se preenche nada por
adivinhacao (CLAUDE.md, secoes 3 e 11.6).
"""

import json
import re
from datetime import date, datetime
from typing import Optional
from zoneinfo import ZoneInfo

import json_repair
from pydantic import BaseModel, Field, ValidationError

FUSO = ZoneInfo("America/Sao_Paulo")

# Campos minimos para que um compromisso possa ser agendado mais tarde
OBRIGATORIOS = ("tipo", "pessoa_idosa", "data", "horario")

FORMATO_DATA = re.compile(r"^\d{4}-\d{2}-\d{2}$")
FORMATO_HORARIO = re.compile(r"^\d{2}:\d{2}$")

# Palavras que afirmam um agendamento que ainda nao acontece nesta etapa
AFIRMA_AGENDAMENTO = re.compile(
    r"\b(agendei|agendado|agendada|marquei|marcado|marcada|registrei|"
    r"cadastrei|adicionei a agenda|coloquei na agenda)\b",
    re.IGNORECASE,
)


def hoje():
    """Data corrente no fuso do projeto, base para datas relativas."""
    return datetime.now(FUSO).date()


class Compromisso(BaseModel):
    """Compromisso extraido de uma mensagem do grupo."""

    tipo: Optional[str] = Field(
        None, description="consulta, exame, retorno, outro"
    )
    pessoa_idosa: Optional[str] = None
    especialidade: Optional[str] = None
    data: Optional[str] = Field(None, description="AAAA-MM-DD")
    horario: Optional[str] = Field(None, description="HH:MM")
    local: Optional[str] = None
    responsavel: Optional[str] = Field(
        None, description="so quem aceitou explicitamente a tarefa"
    )
    e_compromisso: bool = Field(
        True, description="False quando a mensagem e conversa cotidiana"
    )


def faltantes(compromisso):
    """Campos obrigatorios ainda ausentes."""
    dados = compromisso if isinstance(compromisso, dict) else compromisso.model_dump()

    return [campo for campo in OBRIGATORIOS if not dados.get(campo)]


def problemas_de_formato(compromisso):
    """Erros de formato ou de coerencia nos dados extraidos."""
    dados = compromisso if isinstance(compromisso, dict) else compromisso.model_dump()

    problemas = []

    valor = dados.get("data")
    if valor:
        if not FORMATO_DATA.match(str(valor)):
            problemas.append(f"data fora do formato AAAA-MM-DD: {valor}")
        else:
            try:
                if date.fromisoformat(valor) < hoje():
                    problemas.append(f"data no passado: {valor}")
            except ValueError:
                problemas.append(f"data inexistente no calendario: {valor}")

    valor = dados.get("horario")
    if valor and not FORMATO_HORARIO.match(str(valor)):
        problemas.append(f"horario fora do formato HH:MM: {valor}")

    return problemas


def interpretar_json(texto):
    """Le o JSON produzido pelo agente.

    O CrewAI usa o instructor para saida estruturada, mas a versao do
    instructor deste ambiente e incompativel com o mcp que o CrewAI exige
    (mcp~=1.28.1). Por isso o agente devolve JSON em texto e o parse fica
    aqui, com o json_repair tolerando as falhas comuns de LLM: cerca de
    markdown, virgula sobrando, aspas trocadas.
    """
    bruto = str(texto).strip()

    # Remove a cerca de markdown, quando o agente devolve ```json ... ```
    bruto = re.sub(r"^```(?:json)?\s*|\s*```$", "", bruto, flags=re.MULTILINE)

    try:
        dados = json_repair.loads(bruto)
    except (ValueError, json.JSONDecodeError):
        return None

    return dados if isinstance(dados, dict) else None


def validar_extracao(saida):
    """Guardrail do agente de interpretacao.

    O CrewAI reexecuta a tarefa com a mensagem de erro quando falha, e usa
    o valor devolvido aqui como saida da tarefa.
    """
    dados = interpretar_json(saida)

    if dados is None:
        return (
            False,
            "A saida nao e um objeto JSON. Responda apenas com o JSON do "
            "compromisso, sem texto antes ou depois.",
        )

    try:
        compromisso = Compromisso(**dados)
    except ValidationError as erro:
        campos = ", ".join(str(e["loc"][0]) for e in erro.errors())
        return (
            False,
            f"Campos invalidos no JSON: {campos}. "
            "Use exatamente os campos previstos e deixe nulo o que a "
            "mensagem nao informar.",
        )

    problemas = problemas_de_formato(compromisso)

    if problemas:
        return (
            False,
            "Corrija os campos: " + "; ".join(problemas) + ". "
            "Use AAAA-MM-DD para data e HH:MM para horario. "
            "Se a mensagem nao informar o dado, deixe o campo nulo em vez "
            "de deduzir um valor.",
        )

    # Devolve o JSON normalizado: e o que o agente 2 recebe pelo context
    return (
        True,
        json.dumps(compromisso.model_dump(), ensure_ascii=False, indent=2),
    )


def validar_resposta(saida):
    """Guardrail do agente de coordenacao.

    Nesta etapa nada e gravado em agenda nenhuma, entao a resposta nao pode
    afirmar que o compromisso foi agendado (CLAUDE.md, secao 4).
    """
    texto = str(saida).strip()

    encontrados = sorted(set(m.lower() for m in AFIRMA_AGENDAMENTO.findall(texto)))

    if encontrados:
        return (
            False,
            "A resposta afirma um agendamento que nao aconteceu "
            "(" + ", ".join(encontrados) + "). "
            "Esta etapa apenas organiza a informacao e confirma com o grupo. "
            "Reescreva sem dizer que o compromisso foi agendado ou registrado.",
        )

    return (True, texto)
