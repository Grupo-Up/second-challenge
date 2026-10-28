
"""Verifica a fiacao das crews, sem gastar chamada de LLM.

Monta as duas crews e inspeciona os objetos. Roda em um segundo e nao
consome cota do Groq, entao pode ser usado a cada alteracao nos .jsonc.

Existe porque as falhas abaixo NAO levantam excecao -- produzem
comportamento errado que parece capricho do modelo:

  - guardrail escrito como string simples vira LLMGuardrail, e a validacao
    deterministica de data no passado some
  - crew guardada em variavel de modulo faz pedidos concorrentes
    compartilharem Task, e a resposta de um grupo vaza no outro
  - decoradores @agent/@task reintroduzem memoizacao: vazamento de memoria
    com o compromisso dentro, e risco de servir o agente do pedido anterior
  - llm trocado por string devolve temperature e max_tokens ao padrao, e com
    limite baixo o CrewAI recebe texto vazio
  - placeholder removido de um prompt faz o dado parar de chegar na tarefa
  - context voltando a existir na tarefa de resposta a faria enxergar mais
    do que o compromisso fundido

Nao avalia qualidade de prompt nem corretude da extracao: garante a fiacao,
nao o conteudo. Para isso, mande uma mensagem no grupo ou chame a API com
curl -- ela devolve o compromisso estruturado junto com a resposta.
"""

import sys

from crewai.tasks.llm_guardrail import LLMGuardrail
import crewai.project.utils as project_utils

import agentes
from agentes import CREW_EXTRAIR, CREW_RESPONDER, montar_crew

# O console do Windows usa cp1252 e quebra nos caracteres tipograficos
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

falhas = []
total = 0


def checar(descricao, condicao, detalhe=""):
    global total
    total += 1

    if condicao:
        print(f"[ok] {descricao}")
    else:
        print(f"[FALHOU] {descricao}" + (f" -- {detalhe}" if detalhe else ""))
        falhas.append(descricao)


crew_extrair = montar_crew(CREW_EXTRAIR)
crew_responder = montar_crew(CREW_RESPONDER)

extrair = crew_extrair.tasks[0]
responder = crew_responder.tasks[0]

# 1. Os guardrails sao as funcoes Python, nao um juiz de LLM
checar(
    "guardrails sao funcoes Python",
    not isinstance(extrair._guardrail, LLMGuardrail)
    and not isinstance(responder._guardrail, LLMGuardrail),
    'algum virou LLMGuardrail: confira se o .jsonc usa {"python": ...}',
)

# 2. Cada carregamento devolve objetos proprios
outra = montar_crew(CREW_EXTRAIR)
checar(
    "crews isoladas entre carregamentos",
    crew_extrair.agents[0] is not outra.agents[0]
    and extrair is not outra.tasks[0],
    "duas crews compartilham objetos: pedidos concorrentes se misturariam",
)

# 3. A tarefa de resposta nao enxerga nada alem do que recebe por inputs
checar(
    "responder sem context",
    responder.context == [],
    f"context e {responder.context!r}: a tarefa veria mais que o compromisso",
)

# 4. Os placeholders que o agentes.py preenche existem nos prompts
esperados_extrair = ("{mensagem}", "{data_mensagem}", "{pendente}")
faltando = [p for p in esperados_extrair if p not in extrair.description]
checar(
    "placeholders de extrair presentes",
    not faltando,
    f"faltam {faltando}: o dado nao chegaria na tarefa",
)

checar(
    "placeholder de responder presente",
    "{compromisso}" in responder.description,
    "sem {compromisso} a tarefa responderia sobre nada",
)

# 5. Ordem dos placeholders: {mensagem} antes de {pendente}.
# O CrewAI substitui em ordem de aparicao sobre o texto acumulado.
checar(
    "{mensagem} vem antes de {pendente}",
    extrair.description.index("{mensagem}") < extrair.description.index("{pendente}"),
    "o pendente seria interpolado antes e poderia conter o outro literal",
)

# 6. Nada foi memoizado no cache global do modulo project
for _ in range(20):
    montar_crew(CREW_EXTRAIR)
checar(
    "nada memoizado (cache vazio)",
    len(project_utils.cache._cache) == 0,
    f"{len(project_utils.cache._cache)} entradas: algum decorador voltou",
)

# 7. O agente usa a LLM compartilhada, com os parametros certos
llm = crew_extrair.agents[0].llm
checar(
    "LLM compartilhada, max_tokens=2000",
    llm is agentes.LLM_COMPARTILHADA and llm.max_tokens == 2000,
    "a llm virou string no jsonc e perdeu temperature/max_tokens",
)

print(f"\n{total} verificacoes, {len(falhas)} falhas")

sys.exit(1 if falhas else 0)
