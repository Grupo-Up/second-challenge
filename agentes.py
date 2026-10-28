
"""O agente do MVP e as duas tarefas que ele executa.

A configuracao vive em crew_extrair.jsonc, crew_responder.jsonc e agents/:
persona, prompts e guardrails. Aqui ficam a LLM, o carregamento e a fusao
entre o que estava guardado e o que a mensagem nova trouxe.

As tarefas moram em arquivos separados de proposito. A fusao acontece em
Python, ENTRE as duas: a tarefa de resposta decide o que perguntar olhando
os campos nulos, entao precisa receber o compromisso ja completo. Com as
duas no mesmo arquivo o CrewAI as emendaria, sem ponto onde entrar.

Um agente nesta etapa. O segundo entra quando houver integracao com agenda
de verdade: sera o coordenador que cria eventos no calendario. Por isso
nada aqui pode afirmar que um compromisso foi agendado.
"""

import json
from pathlib import Path

from crewai import LLM
from crewai.project import load_crew
from dotenv import load_dotenv
import crewai.llms.cache as crewai_cache

# O Groq rejeita a chave extra que o CrewAI injeta nas mensagens.
# Precisa vir antes de qualquer construcao de LLM.
crewai_cache.mark_cache_breakpoint = lambda msg: msg

import memoria
from compromisso import (
    coerir,
    deve_fundir,
    faltantes,
    fundir,
    hoje,
    interpretar_json,
)

# Carrega a chave da API
load_dotenv()

# Caminhos relativos a este arquivo, nao ao diretorio de onde se executa:
# assim o uvicorn funciona de qualquer lugar.
AQUI = Path(__file__).parent
CREW_EXTRAIR = AQUI / "crew_extrair.jsonc"
CREW_RESPONDER = AQUI / "crew_responder.jsonc"

# Uma LLM para o processo inteiro, referenciada pelo agents/*.jsonc em
# {"python": "agentes.LLM_COMPARTILHADA"}. Mora aqui porque temperature e
# max_tokens nao sao expressaveis como string de modelo no arquivo.
#
# O gpt-oss-20b e um modelo de raciocinio: parte dos tokens vai para o
# raciocinio interno. Com um limite curto, sobra nada para a resposta e o
# CrewAI recebe texto vazio.
LLM_COMPARTILHADA = LLM(
    model="groq/openai/gpt-oss-20b",
    temperature=0.3,
    max_tokens=2000,
)


def montar_crew(arquivo, verbose=False):
    """Monta uma crew nova a cada pedido, a partir do arquivo indicado.

    Agentes e tarefas guardam o resultado da ultima execucao, entao
    reaproveitar os mesmos objetos entre pedidos simultaneos misturaria o
    contexto de conversas diferentes. O load_crew nao memoiza nada, entao
    cada chamada devolve objetos proprios -- verificado em verificar.py.

    load_crew e chamado aqui dentro, e nao no topo do modulo, porque os
    arquivos referenciam agentes.LLM_COMPARTILHADA: no topo o import seria
    circular e pegaria este modulo pela metade.
    """
    crew, _ = load_crew(arquivo)
    crew.verbose = verbose

    return crew


def _higienizar(mensagem):
    """Neutraliza chaves no texto que veio do WhatsApp.

    A mensagem vira entrada de template, e o CrewAI substitui placeholders
    em ordem de aparicao sobre o texto ja acumulado. Alguem escrevendo
    '{pendente}' na conversa faria o literal ser trocado depois.
    """
    return str(mensagem).replace("{", "(").replace("}", ")")


def _extrair(mensagem, data_mensagem, pendente, verbose=False):
    """Tarefa 1: o que ESTA mensagem informa, sem olhar o pendente."""
    saida = montar_crew(CREW_EXTRAIR, verbose).kickoff(
        inputs={
            "mensagem": _higienizar(mensagem),
            "data_mensagem": str(data_mensagem or hoje()),
            "pendente": (
                json.dumps(pendente, ensure_ascii=False, indent=2)
                if pendente
                else "(nenhum)"
            ),
        }
    )

    return interpretar_json(saida.raw) or {}


def _responder(compromisso, verbose=False):
    """Tarefa 2: a resposta ao grupo, a partir do compromisso ja fundido."""
    saida = montar_crew(CREW_RESPONDER, verbose).kickoff(
        inputs={
            "compromisso": json.dumps(compromisso, ensure_ascii=False, indent=2),
        }
    )

    return saida.raw


def _guardar(grupo_id, compromisso):
    """Decide o que fica guardado depois de responder."""
    if grupo_id is None:
        return

    if not compromisso.get("e_compromisso"):
        # Conversa cotidiana nao mexe no que estava pendente
        return

    # Completo exige responsavel, nao so os campos obrigatorios: o caso do
    # CLAUDE.md secao 3 so termina quando alguem assume o acompanhamento.
    if not faltantes(compromisso) and compromisso.get("responsavel"):
        memoria.salvar_pendente(grupo_id, None)
        return

    memoria.salvar_pendente(grupo_id, compromisso)


def _processar(mensagem, data_mensagem, grupo_id, verbose=False):
    pendente = memoria.carregar_pendente(grupo_id)

    novo = _extrair(mensagem, data_mensagem, pendente, verbose)

    if deve_fundir(pendente, novo):
        atual = fundir(pendente, novo)
        usou_pendente = True
    else:
        # Compromisso diferente substitui o pendente; conversa cotidiana
        # passa adiante sem mexer em nada (o _guardar ignora)
        atual = novo
        usou_pendente = False

    # Invariantes antes de responder: a tarefa 2 le estes campos para
    # decidir o que perguntar, entao nao pode receber estado contraditorio
    atual = coerir(atual)

    resposta = _responder(atual, verbose)

    _guardar(grupo_id, atual)

    return {
        "resposta": resposta,
        "compromisso": atual,
        "usou_pendente": usou_pendente,
    }


def processar(mensagem, data_mensagem=None, grupo_id=None, verbose=False):
    """Executa as duas tarefas sobre uma mensagem do grupo.

    Devolve a resposta ao grupo, o compromisso estruturado e se a memoria
    foi usada.

    grupo_id=None desliga a memoria: cada mensagem vira um pedido
    independente, como antes. E o fallback quando a API recebe um pedido
    sem grupo -- um curl de teste, por exemplo.
    """
    if grupo_id is None:
        return _processar(mensagem, data_mensagem, None, verbose)

    # Lock segurado durante o processar inteiro: o perigo nao e o
    # dicionario, e a janela entre carregar e salvar, que atravessa duas
    # chamadas de LLM.
    with memoria.trava(grupo_id):
        return _processar(mensagem, data_mensagem, grupo_id, verbose)
