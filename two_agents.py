
"""Demonstracao dos dois agentes colaborando.

O agente 1 extrai o compromisso da mensagem; o agente 2 recebe essa saida
pelo context e escreve a resposta ao grupo, apontando o que falta.

Cobre tres situacoes: mensagem completa, mensagem incompleta e conversa
cotidiana sem compromisso.
"""

import sys

from agentes import processar
from compromisso import faltantes, hoje

# O console do Windows usa cp1252 e quebra nos caracteres tipograficos
# que a LLM costuma devolver
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MENSAGENS = [
    "A vo Helena tem consulta no cardiologista quinta-feira as 15h, "
    "na clinica do centro.",

    "Marquei o exame da vo Helena, mas ainda nao sei o dia.",

    "Bom dia, pessoal! Alguem viu o jogo ontem?",
]

for mensagem in MENSAGENS:
    print("\n" + "=" * 60)
    print("MENSAGEM DO GRUPO:")
    print(mensagem)

    resultado = processar(mensagem, hoje())
    compromisso = resultado["compromisso"]

    print("\nAGENTE 1 - COMPROMISSO EXTRAIDO:")
    if compromisso:
        for campo, valor in compromisso.items():
            print(f"  {campo}: {valor}")

        pendentes = faltantes(compromisso)
        print("  campos ausentes: " + (", ".join(pendentes) if pendentes else "nenhum"))
    else:
        print("  nada estruturado")

    print("\nAGENTE 2 - RESPOSTA AO GRUPO:")
    print(resultado["resposta"])
