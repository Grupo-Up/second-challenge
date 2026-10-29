
"""Agente 2: coordenacao com o grupo.

Recebe o compromisso estruturado pelo agente 1 e escreve a resposta ao
grupo: o que ficou entendido e o que ainda falta.
"""

from crewai import Agent


def criar_coordenador(llm):
    """Monta o agente. A LLM vem da crew, que e quem a configura."""
    return Agent(
        role="Coordenador de Cuidados",
        goal=(
            "Confirmar com o grupo o que foi entendido e pedir exatamente o "
            "que falta para o compromisso ficar completo"
        ),
        backstory=(
            "Voce e um assistente automatico de um grupo de apoio a uma pessoa "
            "idosa. Voce nao participa dos cuidados, nao opina sobre saude e "
            "nao escolhe quem vai acompanhar quem. Seu papel e devolver ao "
            "grupo um resumo curto do que foi combinado e uma pergunta clara "
            "quando algo ficou em aberto."
        ),
        llm=llm,
        verbose=True,
        allow_delegation=False,
        max_rpm=7999,
        max_iter=2,
        # memory=True,
    )