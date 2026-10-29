
"""Agente 1: interpretacao e validacao da conversa.

Le a mensagem do grupo e devolve um compromisso estruturado. Nao preenche
nada por deducao: o que a mensagem nao disser fica nulo (CLAUDE.md,
secoes 3 e 11.6).
"""

from crewai import Agent


def criar_interprete(llm):
    """Monta o agente. A LLM vem da crew, que e quem a configura."""
    return Agent(
        role="Interprete de Compromissos",
        goal=(
            "Identificar, nas mensagens de um grupo familiar, compromissos de "
            "cuidado de uma pessoa idosa e extrair seus dados sem adivinhar "
            "nada"
        ),
        backstory=(
            "Voce apoia familias que combinam consultas e exames pelo grupo de "
            "mensagens. Voce le a mensagem e separa o que foi realmente dito "
            "do que apenas parece provavel. Quando um dado nao aparece na "
            "mensagem, voce deixa o campo nulo: um campo vazio e corrigivel, "
            "um dado inventado leva a familia a um compromisso errado."
        ),
        llm=llm,
        verbose=True,
        allow_delegation=False,
        max_rpm=7999,
        max_iter=2,
        # memory=True,
    )
