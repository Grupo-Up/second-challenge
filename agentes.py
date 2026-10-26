
"""Os dois agentes do MVP e a crew que os faz colaborar.

Agente 1 interpreta a mensagem do grupo e devolve um compromisso
estruturado. Agente 2 coordena: aponta o que ja esta confirmado, o que
falta e quem precisa responder.

Gravar o compromisso na agenda e uma etapa seguinte, ainda nao
implementada. Por isso o agente 2 nao pode afirmar que agendou nada.
"""

from crewai import Agent, Task, Crew, Process, LLM
from dotenv import load_dotenv
import crewai.llms.cache as crewai_cache
crewai_cache.mark_cache_breakpoint = lambda msg: msg

from compromisso import (
    hoje,
    interpretar_json,
    validar_extracao,
    validar_resposta,
)

# Carrega a chave da API
load_dotenv()

# Configura a LLM hospedada no Groq.
# O gpt-oss-20b e um modelo de raciocinio: parte dos tokens vai para o
# raciocinio interno. Com um limite curto, sobra nada para a resposta e o
# CrewAI recebe texto vazio.
llm = LLM(
    model="groq/openai/gpt-oss-20b",
    temperature=0.3,
    max_tokens=2000
)


def criar_interprete():
    """Agente 1: interpretacao e validacao da conversa."""
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
        verbose=False,
        allow_delegation=False,
        max_iter=2
    )


def criar_coordenador():
    """Agente 2: coordenacao com o grupo."""
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
        verbose=False,
        allow_delegation=False,
        max_iter=2
    )


def tarefa_interpretar(agente):
    """Extrai o compromisso estruturado da mensagem."""
    return Task(
        description=(
            "Hoje e {data_mensagem}. Uma pessoa escreveu no grupo familiar: "
            "'{mensagem}'\n\n"
            "Extraia os dados do compromisso. Regras obrigatorias:\n"
            "(1) Use somente o que esta escrito na mensagem. Nao complete "
            "nenhum campo por deducao, probabilidade ou experiencia comum.\n"
            "(2) Datas relativas como 'amanha', 'quinta-feira' ou 'semana que "
            "vem' devem ser convertidas tomando {data_mensagem} como "
            "referencia, no formato AAAA-MM-DD. Se a mensagem nao permitir "
            "determinar a data com certeza, deixe o campo nulo.\n"
            "(3) Horario no formato HH:MM, 24 horas.\n"
            "(4) Preencha 'responsavel' apenas se alguem aceitou "
            "explicitamente a tarefa nesta mensagem. Mencionar uma pessoa nao "
            "e o mesmo que ela ter aceitado.\n"
            "(5) Se a mensagem for conversa cotidiana e nao descrever um "
            "compromisso, marque e_compromisso como false e deixe os demais "
            "campos nulos."
        ),
        expected_output=(
            "Apenas um objeto JSON, sem texto antes ou depois e sem cerca de "
            "markdown, com exatamente estas chaves: tipo, pessoa_idosa, "
            "especialidade, data, horario, local, responsavel, e_compromisso. "
            "Use null nos dados que a mensagem nao informa."
        ),
        agent=agente,
        guardrail=validar_extracao,
        guardrail_max_retries=2
    )


def tarefa_coordenar(agente, anterior):
    """Transforma o compromisso estruturado em resposta ao grupo."""
    return Task(
        description=(
            "Com base no compromisso extraido na tarefa anterior, escreva a "
            "resposta ao grupo em ate 4 frases. Regras obrigatorias:\n"
            "(1) Escreva na terceira pessoa, como um assistente que organiza a "
            "informacao. Nunca use eu, mim, comigo, meu ou minha.\n"
            "(2) Resuma apenas os dados que foram extraidos. Nao acrescente "
            "local, data, horario, nome ou especialidade que nao estejam ali.\n"
            "(3) Se algum dado obrigatorio estiver nulo (tipo, pessoa idosa, "
            "data ou horario), faca uma pergunta direta pedindo esse dado.\n"
            "(4) Se nao houver responsavel confirmado, pergunte ao grupo quem "
            "podera acompanhar. Nunca atribua a tarefa a alguem.\n"
            "(5) Nao diga que o compromisso foi agendado, marcado ou "
            "registrado. Nada foi gravado em agenda nesta etapa.\n"
            "(6) Se e_compromisso for false, responda apenas que nenhum "
            "compromisso foi identificado na mensagem."
        ),
        expected_output=(
            "Uma mensagem curta em portugues, na terceira pessoa, com o resumo "
            "do que foi entendido e as perguntas do que falta."
        ),
        agent=agente,
        context=[anterior],
        guardrail=validar_resposta,
        guardrail_max_retries=2
    )


def montar_crew():
    """Monta uma crew nova a cada pedido.

    Agentes e tarefas guardam o resultado da ultima execucao, entao
    reaproveitar os mesmos objetos entre pedidos simultaneos misturaria o
    contexto de conversas diferentes.
    """
    interprete = criar_interprete()
    coordenador = criar_coordenador()

    extrair = tarefa_interpretar(interprete)
    responder = tarefa_coordenar(coordenador, extrair)

    return Crew(
        agents=[interprete, coordenador],
        tasks=[extrair, responder],
        process=Process.sequential,
        verbose=False
    )


def processar(mensagem, data_mensagem=None):
    """Executa a crew sobre uma mensagem do grupo.

    Devolve a resposta ao grupo e o compromisso estruturado.
    """
    crew = montar_crew()

    resultado = crew.kickoff(
        inputs={
            "mensagem": mensagem,
            "data_mensagem": str(data_mensagem or hoje()),
        }
    )

    # A saida da primeira tarefa e o JSON ja normalizado pelo guardrail
    extracao = resultado.tasks_output[0]

    return {
        "resposta": resultado.raw,
        "compromisso": interpretar_json(extracao.raw),
    }
