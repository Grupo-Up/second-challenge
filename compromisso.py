
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

# Campos que distinguem um compromisso de outro. Uma mensagem que nao traz
# nenhum deles nao descreve compromisso proprio -- so pode estar
# completando o que ja existia.
IDENTIDADE = ("tipo", "pessoa_idosa", "data")

FORMATO_DATA = re.compile(r"^\d{4}-\d{2}-\d{2}$")
FORMATO_HORARIO = re.compile(r"^\d{2}:\d{2}$")

# Palavras que afirmam um agendamento que ainda nao acontece nesta etapa.
#
# Precisa cobrir a terceira pessoa ("o assistente registrou"), e nao so a
# primeira: a regra (1) do prompt de resposta OBRIGA terceira pessoa, entao
# um regex so com "registrei" nunca dispararia na pratica.
AFIRMA_AGENDAMENTO = re.compile(
    r"\b("
    r"agende[ei]|agendou|agendad[oa]|"
    r"marque[ei]|marcou|marcad[oa]|"
    r"registre[ei]|registrou|registrad[oa]|"
    r"cadastre[ei]|cadastrou|cadastrad[oa]|"
    r"anotou|anotad[oa]|"
    r"(?:adicionei|adicionou|coloquei|colocou) na agenda"
    r")\b",
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
    refere_se_ao_pendente: bool = Field(
        False,
        description=(
            "True quando a mensagem completa ou corrige o compromisso "
            "pendente do grupo, em vez de descrever um novo"
        ),
    )
    alguem_se_ofereceu: bool = Field(
        False,
        description=(
            "True quando alguem se ofereceu para acompanhar mas nao se "
            "identificou pelo nome, como em 'eu levo ela'. O sistema nao "
            "atribui a tarefa sozinho (CLAUDE.md secao 6): pede o nome"
        ),
    )


def faltantes(compromisso):
    """Campos obrigatorios ainda ausentes."""
    dados = compromisso if isinstance(compromisso, dict) else compromisso.model_dump()

    return [campo for campo in OBRIGATORIOS if not dados.get(campo)]


def fundir(pendente, novo):
    """Junta o compromisso pendente com o que a mensagem nova trouxe.

    Duas regras, e so:
      - valor nao nulo em 'novo' sobrescreve  -> permite correcao
        ("na verdade e as 16h")
      - valor nulo em 'novo' nao apaga        -> permite completar
        ("eu levo ela" nao derruba a data que ja estava la)

    Nunca inventa campo e nunca apaga campo confirmado. E por isso que a
    fusao e Python e nao prompt: um modelo que "resume" o pendente pode
    devolver horario nulo, e nulo e um valor perfeitamente valido --
    nenhum guardrail pegaria.
    """
    if not pendente:
        return dict(novo)

    fundido = dict(pendente)

    # Os tres sinalizadores descrevem a mensagem atual, nao o compromisso.
    # Nao sao fundidos: valem so para esta rodada.
    sinalizadores = ("e_compromisso", "refere_se_ao_pendente", "alguem_se_ofereceu")

    for campo in Compromisso.model_fields:
        if campo in sinalizadores:
            continue

        valor = novo.get(campo)
        if valor is not None:
            fundido[campo] = valor

    fundido["e_compromisso"] = True
    fundido["refere_se_ao_pendente"] = False
    fundido["alguem_se_ofereceu"] = bool(novo.get("alguem_se_ofereceu"))

    return fundido


def coerir(compromisso):
    """Aplica as invariantes do registro, depois da fusao.

    Hoje so uma: quem se ofereceu e foi identificado deixa de ser "alguem".
    Com responsavel preenchido, alguem_se_ofereceu ligado faria a resposta
    dizer que alguem se ofereceu E que a tarefa ja tem dono -- as duas
    coisas sobre a mesma pessoa.
    """
    coerente = dict(compromisso)

    if coerente.get("responsavel"):
        coerente["alguem_se_ofereceu"] = False

    return coerente


def deve_fundir(pendente, novo):
    """Se a fusao se aplica. A LLM propoe; aqui a regra fecha.

    A LLM erra refere_se_ao_pendente cerca de uma vez a cada cinco, e
    quando erra a conversa quebra: "eu, Maysa irei levar a minha vo" vira
    um compromisso novo e vazio, e o grupo perde data, horario e local.

    Por isso o campo e tratado como palpite, nao como decisao. Mesmo com
    ele false, duas regras deterministicas ainda fundem:

      - a mensagem nao traz NENHUM campo de identidade -> nao descreve
        compromisso proprio, so pode estar completando o pendente
      - os campos de identidade que ela traz BATEM com o pendente -> e o
        mesmo compromisso, dito de novo

    So vira compromisso novo quando ha conflito real de identidade.
    """
    if not pendente:
        return False

    if not novo.get("e_compromisso"):
        return False

    if novo.get("refere_se_ao_pendente"):
        return True

    # A LLM disse que nao se refere. Confere antes de acreditar.
    trazidos = {
        campo: novo[campo]
        for campo in IDENTIDADE
        if novo.get(campo) is not None
    }

    if not trazidos:
        return True

    return all(pendente.get(campo) == valor for campo, valor in trazidos.items())


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
