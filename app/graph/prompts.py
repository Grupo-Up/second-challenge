
"""O que se pede a cada agente.

Separado de `app/agents/`, que guarda quem e o agente. A persona muda
pouco; estas instrucoes mudam a cada ajuste de regra. Em arquivos
diferentes, mexer numa regra nao arrisca a outra.

As respostas fixas no fim do arquivo nao passam por LLM nenhuma: quando a
mensagem nao e de cuidado, nao ha o que resumir nem o que perguntar, entao
o grafo responde direto.
"""

# ---------------------------------------------------------------------------
# Agente 1 - interpretacao
# ---------------------------------------------------------------------------

PROMPT_INTERPRETAR = (
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
    "(4a) Quem escreveu esta mensagem foi: {autor}. Se a pessoa aceitou "
    "a tarefa em primeira pessoa - 'eu levo', 'eu acompanho', 'deixa "
    "comigo', 'pode deixar que eu vou' -, o responsavel e ela, e voce "
    "escreve esse nome no campo. Se o autor for 'desconhecido', nao "
    "preencha o campo a partir de 'eu': deixe nulo.\n"
    "(4b) Vale igual quando a pessoa escreve o proprio nome em terceira "
    "pessoa. Se o autor e 'Maysa' e a mensagem diz 'a maysa acompanhara "
    "a vo helena', quem se comprometeu foi a propria autora: preencha "
    "responsavel='Maysa'. Compare ignorando maiusculas e sobrenome.\n"
    "(4c) Se a mensagem indica OUTRA pessoa, diferente do autor - 'a ana "
    "leva ela' escrito por Maysa -, deixe responsavel nulo. Essa pessoa "
    "nao falou e nao pode ser comprometida por terceiros.\n"
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
    "extraido.\n"
    "(7) 'tipo' e 'especialidade' sao campos diferentes e nao se "
    "repetem:\n"
    "   'tipo' e a natureza do compromisso. Aceita exatamente: consulta, "
    "exame, retorno, vacina, fisioterapia, terapia, cirurgia, "
    "internacao, medicacao, outro.\n"
    "   'especialidade' e a area medica, quando a mensagem disser: "
    "cardiologia, oftalmologia, ortopedia e assim por diante. Converta o "
    "nome do profissional para a area: 'cardiologista' vira "
    "'cardiologia'.\n"
    "   'consulta' e um tipo, nunca uma especialidade. Se a mensagem so "
    "disser 'consulta', preencha tipo='consulta' e deixe especialidade "
    "nula.\n"
    "(8) 'remarcacao' e true apenas quando a mensagem diz que algo ja "
    "combinado MUDOU: 'na verdade e dia 25', 'foi remarcada para as 16h', "
    "'mudou de medico'. Vale tambem quando o assistente perguntou se era "
    "remarcacao e a mensagem confirma que sim. Em qualquer outro caso, "
    "false - inclusive quando a mensagem apenas acrescenta um dado que "
    "ainda faltava.\n\n"
    "FORMATO DA RESPOSTA: "
    "Apenas um objeto JSON, sem texto antes ou depois e sem cerca de "
    "markdown, com exatamente estas chaves: tipo, pessoa_idosa, "
    "especialidade, data, horario, local, responsavel, classificacao. "
    "Use null nos dados que a mensagem nao informa."
)


# ---------------------------------------------------------------------------
# Agente 2 - coordenacao
# ---------------------------------------------------------------------------

PROMPT_COORDENAR = (
    "Este e o compromisso ja extraido e validado da mensagem do grupo:\n"
    "{compromisso}\n\n"
    "Escreva a resposta ao grupo em ate 4 frases. Voce nao recebe a "
    "mensagem original, apenas os dados acima. Regras obrigatorias:\n"
    "(1) Escreva na terceira pessoa, como um assistente que organiza a "
    "informacao. Nunca use eu, mim, comigo, meu ou minha.\n"
    "(2) Resuma apenas os dados que foram extraidos. Nao acrescente "
    "local, data, horario, nome ou especialidade que nao estejam ali.\n"
    "(2a) A data ja vem escrita por extenso, pronta para uso. Copie ela "
    "exatamente como esta. Nunca reescreva, recalcule ou ajuste o dia, o "
    "mes ou o ano.\n"
    "(3) Se algum dado obrigatorio estiver nulo (tipo, pessoa idosa, "
    "data ou horario), faca uma pergunta direta pedindo esse dado.\n"
    "(4) Se nao houver responsavel confirmado, pergunte ao grupo quem "
    "podera acompanhar. Nunca atribua a tarefa a alguem.\n"
    "(5) Nao diga que o compromisso foi agendado, marcado ou "
    "registrado. Nada foi gravado em agenda nesta etapa.\n\n"
    "FORMATO DA RESPOSTA: "
    "Uma mensagem curta em portugues, na terceira pessoa, com o resumo "
    "do que foi entendido e as perguntas do que falta. Sem cerca de "
    "markdown e sem titulo."
)


# As ultimas falas do grupo, para o agente resolver a quem "ela" e "essa
# consulta" se referem, e para ler a resposta a uma pergunta que o proprio
# assistente fez.
HISTORICO = (
    "\n\nULTIMAS FALAS DESTE GRUPO, da mais antiga para a mais recente:\n"
    "{conversa}\n"
    "Use estas falas apenas para entender a quem a mensagem se refere. "
    "Extraia somente o que a mensagem nova diz: nao traga de volta dado de "
    "fala antiga, porque o sistema ja guardou o que foi extraido antes."
)


# Vai junto do pedido quando o assistente perguntou se era remarcacao e
# espera a resposta. Uma regra geral no meio do prompt nao basta: o modelo
# le o bloco do historico, que manda nao trazer dado de fala antiga, e
# deixa remarcacao em false. Perguntado de forma direta, ele acerta.
CONFIRMACAO_PENDENTE = (
    "\n\nATENCAO - o assistente perguntou ao grupo se esta informacao era "
    "remarcacao do mesmo compromisso ou um compromisso diferente:\n"
    "{pendente}\n"
    "Esta mensagem pode ser a resposta a essa pergunta. Se ela confirma "
    "que foi remarcacao - 'sim', 'isso', 'foi remarcada', 'mudou mesmo', "
    "'e o mesmo' -, marque remarcacao=true. Se ela diz que sao "
    "compromissos diferentes, marque remarcacao=false. Se ela nao "
    "responde a pergunta, siga as regras normais."
)


# Vai junto do pedido quando o grupo ja tem um compromisso em aberto.
# Sem isso o agente le cada mensagem isolada e "a maysa a acompanhara"
# vira 'conversa': sozinha, a frase nao fala de saude nenhuma.
CONTEXTO_EM_ABERTO = (
    "\n\nCONTEXTO: este grupo ja vinha combinando um compromisso de "
    "cuidado, ainda em aberto:\n{compromisso}\n"
    "Se a mensagem acima complementa esse compromisso - informando quem "
    "acompanha, o horario, o local ou qualquer dado que faltava -, "
    "classifique como 'cuidado' e extraia apenas o que a mensagem nova "
    "acrescenta. Nao repita os campos que ja estao no contexto: deixe-os "
    "nulos, pois o sistema ja os tem. Se a mensagem claramente nao tem "
    "relacao com esse compromisso, classifique normalmente."
)


# Reexecucao depois de um guardrail reprovar. Entra como mensagem nova na
# conversa com a LLM, com o erro que o guardrail devolveu.
PROMPT_CORRIGIR = (
    "A resposta anterior foi reprovada na validacao automatica.\n"
    "Motivo: {erro}\n\n"
    "Reescreva a resposta corrigindo exatamente esse ponto, mantendo "
    "todas as regras do pedido original."
)


# ---------------------------------------------------------------------------
# Comando !andamento: alguem do grupo perguntou alguma coisa.
PROMPT_ANDAMENTO = (
    "Alguem do grupo perguntou: '{pergunta}'\n\n"
    "Este e o compromisso que o grupo vem combinando:\n{compromisso}\n\n"
    "Responda em ate 3 frases. Regras obrigatorias:\n"
    "(1) Use somente os dados acima e as falas do grupo. Nao complete "
    "nada por deducao, probabilidade ou experiencia comum.\n"
    "(2) Se a pergunta e sobre um dado que esta nulo, diga que ele ainda "
    "nao foi informado e pergunte ao grupo qual e. Nunca chute data, "
    "horario, local, especialidade ou nome.\n"
    "(3) A data ja vem escrita por extenso. Copie exatamente como esta.\n"
    "(4) Escreva na terceira pessoa. Nunca use eu, mim, comigo, meu ou "
    "minha.\n"
    "(5) Nao diga que o compromisso foi agendado, marcado ou registrado: "
    "nada foi gravado em agenda nesta etapa.\n"
    "(6) Se a pergunta nao tem relacao com o compromisso, responda que "
    "este assistente so organiza os cuidados de saude da pessoa idosa.\n\n"
    "FORMATO DA RESPOSTA: texto curto em portugues, sem cerca de markdown "
    "e sem titulo."
)

# Perguntaram, mas nao ha compromisso nenhum para consultar. Resposta
# deterministica: sem compromisso, nao ha o que a LLM possa responder sem
# inventar.
RESPOSTA_SEM_COMPROMISSO = (
    "Nenhum compromisso em aberto neste grupo. Use !agenda para informar "
    "uma consulta, exame ou retorno."
)

RESPOSTA_FALHA_ANDAMENTO = (
    "Nao foi possivel responder a pergunta agora. Use !compromisso para "
    "ver o que esta combinado."
)


# Respostas que nao passam por LLM
# ---------------------------------------------------------------------------

# Quando a classificacao nao e 'cuidado' nao ha resumo a fazer nem pergunta
# a formular. No CrewAI isso custava uma chamada de LLM inteira para
# devolver uma frase fixa; no grafo e um no deterministico.
RESPOSTA_FIXA = {
    "conversa": "Nenhum compromisso foi identificado na mensagem.",
    "fora_do_escopo": (
        "Este assistente organiza apenas os cuidados de saude da pessoa "
        "idosa, como consultas, exames e retornos. Esse compromisso fica "
        "fora do que ele acompanha."
    ),
}

# A mensagem nova contradiz o que o grupo ja tinha combinado. Pode ser
# remarcacao ou um segundo compromisso - o sistema nao sabe distinguir os
# dois, entao pergunta em vez de escolher (CLAUDE.md, secao 4 e 6).
RESPOSTA_CONFLITO = (
    "Esta informacao nao bate com o que ja estava combinado "
    "({divergencias}). Isso e uma remarcacao do mesmo compromisso ou um "
    "compromisso diferente? Nada foi alterado ate alguem confirmar."
)

# O agente nao conseguiu produzir uma saida valida dentro do limite de
# tentativas. A resposta assume a falha em vez de arriscar um dado errado.
RESPOSTA_FALHA_EXTRACAO = (
    "Nao foi possivel entender o compromisso desta mensagem. Pode "
    "reescrever informando o tipo de compromisso, a pessoa, a data e o "
    "horario?"
)

RESPOSTA_FALHA_COORDENACAO = (
    "O compromisso foi entendido, mas nao foi possivel montar a resposta "
    "ao grupo desta vez. Nada foi gravado em agenda."
)
