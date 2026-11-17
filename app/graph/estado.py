
"""O estado que atravessa o grafo.

Cada chamada de `processar()` cria um estado novo e ele percorre os nos ate
o fim. Nenhum no guarda dado entre execucoes: o que um no sabe esta aqui
dentro, e so aqui.

Campos de erro e de tentativa existem porque os guardrails deixaram de ser
parametro de framework e viraram nos do grafo. O erro do guardrail volta ao
no do agente pelo estado, no lugar do retry automatico que o CrewAI fazia.
"""

import os
from typing import Optional

from typing_extensions import TypedDict

# Com RETER_HISTORICO=1 nada e apagado: o banco guarda cada passo de cada
# execucao, para inspecionar o grafo rodando (CLAUDE.md, secao 9).
# Desligado por padrao: o estado contem dado de saude (secao 8).
#
# Mora aqui, e nao em grafo.py, porque nos.py e grafo.py precisam dela e
# grafo.py importa nos.py - definir la daria import circular.
RETER_HISTORICO = os.environ.get("RETER_HISTORICO") == "1"

# Quantas vezes um agente pode rodar antes de o grafo desistir.
# Equivale ao antigo guardrail_max_retries=2: a primeira execucao mais duas
# correcoes.
MAX_TENTATIVAS = 3

# Teto de voltas do tool-calling do agente 2, equivalente ao max_iter=2 do
# CrewAI. Sem teto, uma LLM teimosa fica pedindo a tool sem parar.
MAX_CHAMADAS = 2

# Campos em que uma mensagem nova pode CONTRADIZER o que ja foi combinado.
# Preencher um campo vazio e acumular; trocar o valor de um campo que ja
# tinha outro e remarcacao ou um segundo compromisso - e o sistema ainda
# nao sabe distinguir os dois, entao pergunta (CLAUDE.md, secao 4).
#
# `responsavel` fica de fora: trocar quem acompanha e combinacao normal do
# grupo, nao sinal de que mudou o compromisso.
CAMPOS_EXCLUDENTES = ("tipo", "pessoa_idosa", "especialidade", "data", "horario", "local")

# Quantas falas ficam no historico do grupo, contando mensagem e resposta.
# 12 da umas seis trocas - o bastante para o agente entender a quem "ela" e
# "essa consulta" se referem, e para ler a resposta a uma pergunta que o
# proprio assistente fez.
#
# O limite existe por dois motivos: o prompt cresce a cada fala guardada, e
# conversa gravada e conteudo bruto, que o CLAUDE.md secao 8 manda evitar.
# Guardar as ultimas falas e um meio-termo: resolve a referencia sem virar
# arquivo da vida do grupo.
MAX_HISTORICO = 12


class EstadoGrupo(TypedDict, total=False):
    """Tudo que o grafo le e escreve durante uma mensagem do grupo."""

    # --- entrada ---
    mensagem: str
    # Data da mensagem, base para resolver "amanha" e "quinta-feira"
    data_mensagem: str
    # Quem escreveu, base para resolver "eu levo ela"
    autor: Optional[str]
    # Comando usado: agenda, compromisso ou andamento. E o que decide por
    # onde a mensagem entra no grafo.
    comando: Optional[str]

    # --- agente 1 ---
    # Texto cru devolvido pela LLM, antes do guardrail
    extracao_bruta: Optional[str]
    # O que ESTA mensagem disse, ja validado pelo guardrail
    extracao: Optional[dict]
    erro_extracao: Optional[str]
    tentativas_extracao: int

    # --- compromisso acumulado ---
    # O que o grupo combinou ate agora, somando as mensagens anteriores.
    # Sobrevive entre chamadas pelo checkpointer, com um thread por grupo.
    compromisso: Optional[dict]
    # Campos em que a mensagem nova contradiz o compromisso acumulado
    conflitos: list[str]
    # A extracao que gerou o conflito, guardada a espera de confirmacao.
    # Sem ela, confirmar a remarcacao na mensagem seguinte nao teria o que
    # aplicar: o dado novo ja teria sido descartado.
    pendente: Optional[dict]
    # Compromisso completo: a proxima mensagem comeca um novo
    encerrado: bool

    # --- historico do grupo ---
    # Ultimas falas, em {"quem": ..., "texto": ...}. Entram as mensagens do
    # grupo e as respostas do assistente: sem as respostas, o agente nao
    # tem como saber que uma fala curta responde a uma pergunta dele.
    historico: list[dict]

    # --- agente 2 ---
    resposta_bruta: Optional[str]
    erro_resposta: Optional[str]
    tentativas_resposta: int
    # O que a tool de agenda devolveu nesta mensagem, se foi chamada. E a
    # unica prova de que algo foi gravado - o guardrail le daqui, nao do
    # que a LLM afirma.
    gravacao: Optional[str]

    # --- saida ---
    resposta: Optional[str]
