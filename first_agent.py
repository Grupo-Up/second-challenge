
"""Demonstracao do agente 1 sozinho: interpretacao da mensagem.

Executa apenas a extracao, para mostrar o que o agente entende de uma
mensagem do grupo antes de qualquer coordenacao.
"""

import sys

from crewai import Crew

from agentes import criar_interprete, tarefa_interpretar
from compromisso import faltantes, hoje, interpretar_json

# O console do Windows usa cp1252 e quebra nos caracteres tipograficos
# que a LLM costuma devolver
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MENSAGEM = (
    "A vo Helena tem consulta no cardiologista quinta-feira as 15h, "
    "na clinica do centro."
)

agente = criar_interprete()
tarefa = tarefa_interpretar(agente)

crew = Crew(
    agents=[agente],
    tasks=[tarefa],
    verbose=True
)

resultado = crew.kickoff(
    inputs={"mensagem": MENSAGEM, "data_mensagem": str(hoje())}
)

compromisso = interpretar_json(resultado.raw)

print("\nMENSAGEM:")
print(MENSAGEM)

print("\nCOMPROMISSO EXTRAIDO:")
if compromisso:
    for campo, valor in compromisso.items():
        print(f"  {campo}: {valor}")

    pendentes = faltantes(compromisso)
    print("\nCAMPOS OBRIGATORIOS AUSENTES:")
    print("  " + (", ".join(pendentes) if pendentes else "nenhum"))
else:
    print(resultado.raw)
