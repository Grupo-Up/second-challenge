
"""O grafo que faz os dois agentes colaborarem.

    __start__ -> interpretar -> validar_extracao
                     ^                 |
                     |  erro           | classificacao
                     +-----------------+
                                       |
          cuidado -> coordenar -> validar_resposta -> __end__
                         ^                 |
                         |  erro           |
                         +-----------------+
          conversa / fora_do_escopo -> resposta_fixa -> __end__

O roteamento fica depois da extracao, nao antes: e o agente 1 que produz o
campo `classificacao`, e so com ele da para saber se vale chamar o agente 2.

Gravar o compromisso na agenda e uma etapa seguinte, ainda nao
implementada. Por isso o agente 2 nao pode afirmar que agendou nada.
"""

import os
import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from app.compromisso import hoje
from app.graph import nos
from app.graph.estado import RETER_HISTORICO, EstadoGrupo


def montar_grafo():
    """Monta o grafo. Chamado uma vez, na importacao do modulo."""
    construtor = StateGraph(EstadoGrupo)

    construtor.add_node("interpretar", nos.interpretar)
    construtor.add_node("validar_extracao", nos.validar_extracao)
    construtor.add_node("fundir", nos.fundir)
    construtor.add_node("perguntar_conflito", nos.perguntar_conflito)
    construtor.add_node("coordenar", nos.coordenar)
    construtor.add_node("validar_resposta", nos.validar_resposta)
    construtor.add_node("encerrar", nos.encerrar)
    construtor.add_node("resposta_fixa", nos.resposta_fixa)
    construtor.add_node("falha_extracao", nos.falha_extracao)
    construtor.add_node("falha_coordenacao", nos.falha_coordenacao)
    construtor.add_node("limpar", nos.limpar)
    construtor.add_node("responder_compromisso", nos.responder_compromisso)
    construtor.add_node("responder_andamento", nos.responder_andamento)
    construtor.add_node("validar_andamento", nos.validar_andamento)
    construtor.add_node("falha_andamento", nos.falha_andamento)

    # O Roteador: o comando decide por onde a mensagem entra. Sem LLM -
    # a pessoa ja disse a intencao ao escolher o comando.
    construtor.add_conditional_edges(
        START,
        nos.rumo_inicial,
        {
            "interpretar": "interpretar",
            "responder_compromisso": "responder_compromisso",
            "responder_andamento": "responder_andamento",
        },
    )

    construtor.add_edge("responder_compromisso", "limpar")
    construtor.add_edge("responder_andamento", "validar_andamento")
    construtor.add_edge("falha_andamento", "limpar")

    construtor.add_conditional_edges(
        "validar_andamento",
        nos.rumo_apos_andamento,
        {
            "responder_andamento": "responder_andamento",
            "falha_andamento": "falha_andamento",
            "limpar": "limpar",
        },
    )

    construtor.add_edge("interpretar", "validar_extracao")
    construtor.add_edge("coordenar", "validar_resposta")

    construtor.add_conditional_edges(
        "validar_extracao",
        nos.rumo_apos_extracao,
        {
            # Guardrail reprovou e ainda ha tentativa: o agente 1 roda de
            # novo, agora com o erro na conversa.
            "interpretar": "interpretar",
            "falha_extracao": "falha_extracao",
            # Passou: o caminho depende da classificacao.
            "fundir": "fundir",
            "resposta_fixa": "resposta_fixa",
        },
    )

    construtor.add_conditional_edges(
        "fundir",
        nos.rumo_apos_fusao,
        {
            "perguntar_conflito": "perguntar_conflito",
            "coordenar": "coordenar",
        },
    )

    construtor.add_conditional_edges(
        "validar_resposta",
        nos.rumo_apos_resposta,
        {
            "coordenar": "coordenar",
            "falha_coordenacao": "falha_coordenacao",
            "encerrar": "encerrar",
        },
    )

    # Todo caminho passa por `limpar` antes do fim: e ele que impede o
    # texto cru da conversa de ficar gravado no checkpoint.
    construtor.add_edge("encerrar", "limpar")
    construtor.add_edge("perguntar_conflito", "limpar")
    construtor.add_edge("resposta_fixa", "limpar")
    construtor.add_edge("falha_extracao", "limpar")
    construtor.add_edge("falha_coordenacao", "limpar")
    construtor.add_edge("limpar", END)

    return construtor


# Onde fica o estado das conversas. Contem dado de saude: o arquivo nao vai
# para o repositorio e o diretorio esta no .gitignore (CLAUDE.md, secao 8).
BANCO = Path(
    os.environ.get("CHECKPOINT_DB", Path(__file__).resolve().parents[2] / "dados" / "conversas.sqlite")
)
BANCO.parent.mkdir(parents=True, exist_ok=True)

# check_same_thread=False porque o uvicorn atende pedidos em threads
# diferentes e a conexao e unica, viva enquanto o processo roda.
_conexao = sqlite3.connect(str(BANCO), check_same_thread=False)

# O checkpointer e o que da memoria ao grafo: ele grava o estado ao fim de
# cada execucao e devolve esse estado na proxima chamada do mesmo thread.
# Sem ele, cada mensagem comecaria do zero.
memoria = SqliteSaver(_conexao)

# O grafo e montado uma vez e reaproveitado entre pedidos. O estado nao
# mora nele: mora no checkpointer, separado por thread.
grafo = montar_grafo().compile(checkpointer=memoria)


def processar(mensagem, data_mensagem=None, grupo=None, autor=None, comando="agenda"):
    """Executa o grafo sobre uma mensagem do grupo.

    `grupo` e o identificador da conversa - no WhatsApp, o JID do grupo.
    Ele vira o `thread_id` do checkpointer: e o que faz "eu levo ela" cair
    no mesmo compromisso da consulta combinada mensagens antes. Sem ele,
    todos os grupos dividiriam um thread so, o que misturaria conversas de
    familias diferentes.
    """
    thread = grupo or "sem-grupo"

    estado = grafo.invoke(
        {
            "mensagem": mensagem,
            "data_mensagem": str(data_mensagem or hoje()),
            "autor": autor,
            "comando": comando or "agenda",
            # Campos de trabalho zerados a cada mensagem. Sem isto, o erro
            # e o contador da mensagem anterior voltariam do checkpointer e
            # o agente comecaria ja "devendo" uma correcao.
            "extracao": None,
            "extracao_bruta": None,
            "erro_extracao": None,
            "tentativas_extracao": 0,
            "resposta": None,
            "resposta_bruta": None,
            "erro_resposta": None,
            "tentativas_resposta": 0,
            "conflitos": [],
        },
        config={"configurable": {"thread_id": thread}},
    )

    resultado = {
        "resposta": estado.get("resposta"),
        "compromisso": estado.get("compromisso"),
        # O que ESTA mensagem foi, para o log da rota. O compromisso
        # acumulado e sempre 'cuidado' e nao serviria para isso.
        "classificacao": (estado.get("extracao") or {}).get("classificacao"),
        "encerrado": bool(estado.get("encerrado")),
    }

    # Compromisso encerrado: o thread nao volta a ser lido - a proxima
    # mensagem do grupo comeca um compromisso novo. Apagar nao muda o
    # comportamento e tira do disco o conteudo daquela conversa.
    if resultado["encerrado"] and not RETER_HISTORICO:
        try:
            memoria.delete_thread(thread)
        except Exception as erro:
            # Falha de limpeza nao pode derrubar uma resposta ja pronta.
            # Loga o tipo do erro, nunca o conteudo da conversa.
            print("falha ao limpar o thread:", type(erro).__name__, flush=True)

    return resultado
