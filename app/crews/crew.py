
"""A crew que faz os dois agentes colaborarem.

Define a LLM, as duas tarefas e a sequencia: o agente 1 extrai o
compromisso da mensagem e o agente 2 recebe essa saida pelo context e
escreve a resposta ao grupo.

Gravar o compromisso na agenda e uma etapa seguinte, ainda nao
implementada. Por isso o agente 2 nao pode afirmar que agendou nada.
"""

from crewai import Task, Crew, Process, LLM
from dotenv import load_dotenv
import crewai.llms.cache as crewai_cache
crewai_cache.mark_cache_breakpoint = lambda msg: msg

from app.agents.coordenador import criar_coordenador
from app.agents.interprete import criar_interprete
from app.compromisso import (
    hoje,
    interpretar_json,
    validar_extracao,
    validar_resposta,
)

# Carrega a chave da API. O .env e procurado a partir do diretorio onde o
# processo foi iniciado, entao os comandos rodam da raiz do projeto.
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
            "(5) O campo 'classificacao' aceita exatamente tres valores, e "
            "voce escolhe um deles:\n"
            "   'cuidado' - a mensagem combina um compromisso de cuidado da "
            "pessoa idosa: consulta, exame, retorno, vacina, fisioterapia, "
            "terapia, cirurgia, internacao, entrega ou troca de medicacao. E "
            "o unico caso em que os demais campos sao preenchidos.\n"
            "   'fora_do_escopo' - a mensagem combina um compromisso futuro "
            "que nao e de cuidado da pessoa idosa, como reuniao de trabalho, "
            "aniversario, viagem, jantar ou jogo do time. Nao tente encaixar "
            "esses compromissos em 'cuidado': eles ficam de fora.\n"
            "   'conversa' - a mensagem apenas comenta, pergunta ou conta "
            "algo que ja aconteceu, sem combinar nada que va acontecer. "
            "Elogio, recado e conversa solta entram aqui, mesmo que citem "
            "almoco, visita ou passeio.\n"
            "(6) Em 'fora_do_escopo' e em 'conversa', deixe todos os demais "
            "campos nulos. Nada do que foi dito nessas mensagens deve ser "
            "extraido."
        ),
        expected_output=(
            "Apenas um objeto JSON, sem texto antes ou depois e sem cerca de "
            "markdown, com exatamente estas chaves: tipo, pessoa_idosa, "
            "especialidade, data, horario, local, responsavel, classificacao. "
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
            "resposta ao grupo em ate 4 frases. Voce nao recebe a mensagem "
            "original, apenas os dados ja extraidos e validados. Regras "
            "obrigatorias:\n"
            "(1) Escreva na terceira pessoa, como um assistente que organiza a "
            "informacao. Nunca use eu, mim, comigo, meu ou minha.\n"
            "(2) Resuma apenas os dados que foram extraidos. Nao acrescente "
            "local, data, horario, nome ou especialidade que nao estejam ali.\n"
            "(2a) A data vem no formato AAAA-MM-DD. Escreva ela por extenso: "
            "dia com dois digitos, mes por nome e ano com quatro digitos. "
            "2026-10-07 vira 07 de outubro de 2026. Os meses, de 01 a 12, "
            "sao janeiro, fevereiro, marco, abril, maio, junho, julho, "
            "agosto, setembro, outubro, novembro e dezembro. Nunca escreva a "
            "data no formato AAAA-MM-DD e nunca mude o dia, o mes ou o ano.\n"
            "(3) Se classificacao for 'cuidado' e algum dado obrigatorio "
            "estiver nulo (tipo, pessoa idosa, data ou horario), faca uma "
            "pergunta direta pedindo esse dado.\n"
            "(4) Se classificacao for 'cuidado' e nao houver responsavel "
            "confirmado, pergunte ao grupo quem podera acompanhar. Nunca "
            "atribua a tarefa a alguem.\n"
            "(5) Nao diga que o compromisso foi agendado, marcado ou "
            "registrado. Nada foi gravado em agenda nesta etapa.\n"
            "(6) Quando classificacao nao for 'cuidado', nao resuma nada e "
            "nao faca nenhuma pergunta. Responda em uma unica frase, decidida "
            "pelo valor do campo:\n"
            "   'conversa' - responda que nenhum compromisso foi identificado "
            "na mensagem.\n"
            "   'fora_do_escopo' - responda que este assistente organiza "
            "apenas os cuidados de saude da pessoa idosa, como consultas, "
            "exames e retornos, e que esse compromisso fica fora do que ele "
            "acompanha. Nao se ofereca para ajudar com ele nem sugira como "
            "organiza-lo."
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
    interprete = criar_interprete(llm)
    coordenador = criar_coordenador(llm)

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
