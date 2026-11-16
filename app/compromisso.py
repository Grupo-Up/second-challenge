
"""Estrutura de um compromisso e as validacoes compartilhadas.

Usado pelos agentes para garantir que a saida da LLM tenha formato
verificavel. Campos desconhecidos ficam em None: nao se preenche nada por
adivinhacao (CLAUDE.md, secoes 3 e 11.6).
"""

import json
import re
from datetime import date, datetime
from typing import Literal, Optional
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


MESES = (
    "janeiro", "fevereiro", "marco", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
)

CONFIRMA_REMARCACAO = re.compile(
    r"\b(sim|isso|exato|confirmo|confirmado|positivo|"
    r"remarcad[ao]|remarcaram|remarcou|mudou|mudaram|alterou|alteraram|"
    r"e o mesmo|eh o mesmo|mesmo compromisso)\b",
    re.IGNORECASE,
)

# Respostas que negam: sao dois compromissos diferentes
NEGA_REMARCACAO = re.compile(
    r"\b(nao|outro|outra|diferente|segundo|segunda consulta|alem)\b",
    re.IGNORECASE,
)


def confirma_remarcacao(texto):
    """A mensagem confirma que foi remarcacao do mesmo compromisso?

    Devolve True, False ou None quando a mensagem nao responde a pergunta.
    A negativa vem primeiro: "nao, e outro exame" tem "outro" e nao pode
    ser lido como confirmacao.
    """
    if not texto:
        return None

    if NEGA_REMARCACAO.search(texto):
        return False

    if CONFIRMA_REMARCACAO.search(texto):
        return True

    return None


def hoje():
    """Data corrente no fuso do projeto, base para datas relativas."""
    return datetime.now(FUSO).date()


def data_por_extenso(iso):
    """Converte AAAA-MM-DD em '11 de novembro de 2026'.

    A conversao era regra de prompt e a LLM errava o dia: o compromisso
    trazia 2026-11-11 e a resposta ao grupo saia "07 de novembro de 2026".
    Escrever a data e conversao mecanica, nao julgamento - fica em codigo,
    onde o resultado e sempre o mesmo.

    Os meses ficam numa tupla porque `locale` em portugues depende de
    pt_BR instalado no sistema, o que nao se pode assumir no Windows.
    """
    if not iso:
        return None

    try:
        data = date.fromisoformat(str(iso))
    except ValueError:
        # Formato invalido ja e barrado por validar_extracao; aqui so
        # devolve como veio, sem mascarar o problema
        return str(iso)

    return f"{data.day:02d} de {MESES[data.month - 1]} de {data.year}"


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
    remarcacao: bool = Field(
        False,
        description=(
            "a mensagem diz que um compromisso ja combinado mudou. So "
            "entao um dado novo pode substituir um dado anterior"
        ),
    )
    classificacao: Literal["cuidado", "fora_do_escopo", "conversa"] = Field(
        "conversa",
        description=(
            "cuidado: compromisso de cuidado da pessoa idosa, o unico caso "
            "que o projeto acompanha. fora_do_escopo: e um compromisso, mas "
            "nao de cuidado. conversa: nao ha compromisso nenhum."
        ),
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

    O agente devolve JSON em texto e o parse fica aqui, com o json_repair
    tolerando as falhas comuns de LLM: cerca de markdown, virgula sobrando,
    aspas trocadas.
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

    Devolve (True, json_normalizado) ou (False, motivo). O no
    `validar_extracao` do grafo usa o motivo para reexecutar o agente com o
    erro na conversa.
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

    # Devolve o JSON normalizado: e o que o agente 2 recebe pelo estado.
    # A data fica em AAAA-MM-DD, que e o formato verificavel pelo regex e o
    # que a API de calendario vai usar. Escrever a data por extenso para o
    # grupo e regra da tarefa do agente 2.
    return (
        True,
        json.dumps(compromisso.model_dump(), ensure_ascii=False, indent=2),
    )


# Mencoes de data e horario no texto de uma resposta. Servem para pegar o
# agente inventando dado que o compromisso nao tem.
MENCIONA_DATA = re.compile(
    r"\b(\d{1,2}\s*/\s*\d{1,2}|" + "|".join(MESES) + r"|março)\b",
    re.IGNORECASE,
)
MENCIONA_HORARIO = re.compile(r"\b\d{1,2}\s*[:h]\s*\d{0,2}\b", re.IGNORECASE)

# Como cada campo aparece no resumo ao grupo
ROTULOS = (
    ("tipo", "Tipo"),
    ("especialidade", "Especialidade"),
    ("pessoa_idosa", "Pessoa"),
    ("data", "Data"),
    ("horario", "Horario"),
    ("local", "Local"),
    ("responsavel", "Quem acompanha"),
)


def resumir(compromisso):
    """Monta o texto do compromisso em aberto, sem LLM nenhuma.

    Deterministico de ponta a ponta: mesma entrada, mesma saida, e nenhuma
    chance de inventar um dado que nao esta ali. E o que responde ao
    comando !compromisso.
    """
    dados = compromisso or {}

    if not any(dados.get(campo) for campo, _ in ROTULOS):
        return "Nenhum compromisso em aberto neste grupo."

    linhas = ["Compromisso em aberto:"]

    for campo, rotulo in ROTULOS:
        valor = dados.get(campo)

        if campo == "data" and valor:
            valor = data_por_extenso(valor)

        linhas.append(f"- {rotulo}: {valor if valor else 'ainda nao informado'}")

    pendentes = faltantes(dados)

    if pendentes:
        linhas.append("")
        linhas.append("Ainda falta: " + ", ".join(pendentes) + ".")

    linhas.append("")
    linhas.append("Nada foi gravado em agenda nesta etapa.")

    return "\n".join(linhas)


def validar_andamento(saida, compromisso):
    """Guardrail da resposta a uma pergunta do grupo.

    Alem do que `validar_resposta` checa, pega o caso proprio da pergunta
    livre: o agente responder "a consulta e dia 12" quando o compromisso
    nao tem data nenhuma. Perguntar nao pode virar porta de entrada para
    dado inventado (CLAUDE.md, secao 7).
    """
    aprovado, texto = validar_resposta(saida)

    if not aprovado:
        return (aprovado, texto)

    dados = compromisso or {}

    if not dados.get("data") and MENCIONA_DATA.search(texto):
        return (
            False,
            "A resposta menciona uma data, mas o compromisso nao tem data "
            "informada. Responda que a data ainda nao foi informada e "
            "pergunte ao grupo qual e.",
        )

    if not dados.get("horario") and MENCIONA_HORARIO.search(texto):
        return (
            False,
            "A resposta menciona um horario, mas o compromisso nao tem "
            "horario informado. Responda que o horario ainda nao foi "
            "informado e pergunte ao grupo qual e.",
        )

    return (True, texto)


def validar_resposta(saida):
    """Guardrail do agente de coordenacao.

    Nesta etapa nada e gravado em agenda nenhuma, entao a resposta nao pode
    afirmar que o compromisso foi agendado (CLAUDE.md, secao 4).

    Devolve (True, texto) ou (False, motivo), no mesmo contrato de
    `validar_extracao`.
    """
    texto = str(saida).strip()

    # Resposta vazia passava: nao tem palavra de agendamento, entao nada
    # era encontrado e o guardrail aprovava. O grupo receberia uma
    # mensagem em branco. Acontece quando o prompt fica longo e o modelo
    # gasta o orcamento de tokens no raciocinio interno.
    if len(texto) < 15:
        return (
            False,
            "A resposta veio vazia ou curta demais. Escreva a mensagem ao "
            "grupo com o resumo do compromisso e as perguntas do que falta.",
        )

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
