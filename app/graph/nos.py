
"""Os nos do grafo.

Cada funcao recebe o estado e devolve apenas os campos que mudou - o
LangGraph funde esse pedaco no estado. Nenhuma funcao aqui guarda dado
entre execucoes.

Os nos se dividem em dois tipos, e a diferenca e o ponto principal da
arquitetura:

- nos de agente (`interpretar`, `coordenar`) chamam a LLM;
- nos de guardrail (`validar_extracao`, `validar_resposta`) sao codigo
  deterministico, reaproveitado de `app/compromisso.py` sem alteracao.

O prompt pede ao agente que nao adivinhe. O guardrail verifica que ele nao
adivinhou.
"""

import json
import os

from dotenv import load_dotenv
from langchain_core.messages import ToolMessage
from langchain_groq import ChatGroq

from app.agents import RAG, coordenador, interprete
from app.compromisso import (
    confirma_remarcacao,
    data_com_dia,
    data_por_extenso,
    faltantes,
    hoje,
    interpretar_json,
    resumir,
    resumir_gravados,
    validar_andamento as checar_andamento,
    validar_extracao as checar_extracao,
    validar_orientacao as checar_orientacao,
    validar_resposta as checar_resposta,
)
from app.graph import prompts
from app.graph.estado import (
    CAMPOS_EXCLUDENTES,
    MAX_CHAMADAS,
    MAX_HISTORICO,
    MAX_TENTATIVAS,
    RETER_HISTORICO,
    EstadoGrupo,
)
from app.tools.agenda import agenda, listar_ativos

# Carrega a chave da API. O .env e procurado a partir do diretorio onde o
# processo foi iniciado, entao os comandos rodam da raiz do projeto.
load_dotenv()

# O gpt-oss-20b e um modelo de raciocinio: parte dos tokens vai para o
# raciocinio interno. Com um limite curto, sobra nada para a resposta e o
# conteudo chega vazio.
#
# reasoning_format="hidden" mantem o raciocinio fora do campo de conteudo.
# Sem isso o JSON do agente 1 viria misturado ao texto do raciocinio e o
# guardrail reprovaria uma saida que estava correta.
llm = ChatGroq(
    model=os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b"),
    temperature=0.3,
    max_tokens=2000,
    reasoning_format="hidden",
)


def _conversar(persona, pedido, resposta_anterior=None, erro=None):
    """Monta a conversa com a LLM e devolve o texto da resposta.

    Numa reexecucao, a saida reprovada e o motivo da reprovacao entram na
    conversa. E o equivalente ao retry que o CrewAI fazia sozinho quando um
    guardrail falhava: o agente ve o proprio erro em vez de tentar de novo
    no escuro.
    """
    mensagens = [
        {"role": "system", "content": persona},
        {"role": "user", "content": pedido},
    ]

    if erro:
        mensagens.append(
            {"role": "assistant", "content": resposta_anterior or ""}
        )
        mensagens.append(
            {"role": "user", "content": prompts.PROMPT_CORRIGIR.format(erro=erro)}
        )

    return str(llm.invoke(mensagens).content).strip()


def _conversar_com_agenda(persona, pedido, resposta_anterior=None, erro=None):
    """Como `_conversar`, mas com a tool de agenda na mao do agente.

    Devolve (texto, gravacao). `gravacao` e o que a tool respondeu, ou None
    se o agente nao a chamou - e o que o guardrail usa para saber se pode
    deixar a resposta afirmar que gravou.
    """
    mensagens = [
        {"role": "system", "content": persona},
        {"role": "user", "content": pedido},
    ]

    if erro:
        mensagens.append({"role": "assistant", "content": resposta_anterior or ""})
        mensagens.append(
            {"role": "user", "content": prompts.PROMPT_CORRIGIR.format(erro=erro)}
        )

    com_tool = llm.bind_tools([agenda])
    resposta = com_tool.invoke(mensagens)

    gravacao = None
    voltas = 0

    while getattr(resposta, "tool_calls", None) and voltas < MAX_CHAMADAS:
        mensagens.append(resposta)

        for chamada in resposta.tool_calls:
            retorno = agenda.invoke(chamada["args"])
            gravacao = retorno

            print("agenda:", chamada["args"].get("acao"), "->", retorno, flush=True)

            mensagens.append(
                ToolMessage(content=retorno, tool_call_id=chamada["id"])
            )

        resposta = com_tool.invoke(mensagens)
        voltas += 1

    return str(resposta.content).strip(), gravacao


# ---------------------------------------------------------------------------
# Agente 1 e seu guardrail
# ---------------------------------------------------------------------------


def interpretar(estado: EstadoGrupo) -> dict:
    """Agente 1: le a mensagem e devolve o JSON do compromisso."""
    pedido = prompts.PROMPT_INTERPRETAR.format(
        data_mensagem=data_com_dia(estado.get("data_mensagem") or hoje()),
        mensagem=estado["mensagem"],
        autor=estado.get("autor") or "desconhecido",
    )

    # As ultimas falas do grupo: e com elas que "ela", "essa consulta" e
    # "sim, foi remarcada" deixam de ser indecifraveis.
    historico = estado.get("historico") or []

    if historico:
        pedido += prompts.HISTORICO.format(
            conversa="\n".join(f"{f['quem']}: {f['texto']}" for f in historico)
        )

    # Compromisso ainda em aberto neste grupo entra como contexto. Sem
    # ele, uma mensagem curta de complemento ("a maysa a acompanhara")
    # seria lida isolada e classificada como conversa.
    aberto = None if estado.get("encerrado") else estado.get("compromisso")

    if aberto:
        pedido += prompts.CONTEXTO_EM_ABERTO.format(
            compromisso=json.dumps(aberto, ensure_ascii=False, indent=2)
        )

    # O assistente perguntou se era remarcacao e espera resposta. A
    # pergunta vai de novo, explicita: so a regra geral do prompt nao
    # bastou - o modelo lia o bloco do historico, que manda nao trazer
    # dado de fala antiga, e deixava remarcacao em false.
    pendente = estado.get("pendente")

    if pendente:
        pedido += prompts.CONFIRMACAO_PENDENTE.format(
            pendente=json.dumps(pendente, ensure_ascii=False, indent=2)
        )

    texto = _conversar(
        interprete.PERSONA,
        pedido,
        resposta_anterior=estado.get("extracao_bruta"),
        erro=estado.get("erro_extracao"),
    )

    return {
        "extracao_bruta": texto,
        "tentativas_extracao": estado.get("tentativas_extracao", 0) + 1,
    }


def validar_extracao(estado: EstadoGrupo) -> dict:
    """Guardrail do agente 1. Codigo deterministico, sem LLM.

    Rejeita JSON malformado, campo fora do modelo `Compromisso`, data fora
    do formato e data no passado.
    """
    aprovado, saida = checar_extracao(estado.get("extracao_bruta") or "")

    if not aprovado:
        return {"erro_extracao": saida, "extracao": None}

    # Escreve em `extracao`, nao em `compromisso`: isto e o que ESTA
    # mensagem disse. Juntar com o que o grupo ja tinha combinado e
    # trabalho do no `fundir`.
    return {
        "erro_extracao": None,
        "extracao_bruta": saida,
        "extracao": interpretar_json(saida),
    }


# ---------------------------------------------------------------------------
# Fusao com o que o grupo ja combinou
# ---------------------------------------------------------------------------


def fundir(estado: EstadoGrupo) -> dict:
    """Junta a mensagem nova ao compromisso que o grupo ja vinha montando.

    Codigo deterministico, sem LLM. A regra e simples e conservadora:
    campo que a mensagem nova informa entra; campo que ela deixa nulo
    preserva o valor anterior. Nada e apagado por omissao - quem nao
    mencionou o horario nao esta cancelando o horario.

    Se a mensagem nova CONTRADIZ um campo que ja tinha outro valor, nao
    funde: marca o conflito e deixa o grafo perguntar. Pode ser remarcacao
    ou um segundo compromisso, e o sistema ainda nao sabe distinguir os
    dois (CLAUDE.md, secao 4). Fundir no escuro misturaria duas consultas
    numa so.
    """
    # Compromisso anterior encerrado: a mensagem nova comeca do zero
    anterior = {} if estado.get("encerrado") else (estado.get("compromisso") or {})
    extracao = estado.get("extracao") or {}

    def aplicar(base, novo):
        """Copia sobre a base o que `novo` informa, ignorando nulos."""
        for campo, valor in novo.items():
            # `remarcacao` descreve a mensagem, nao o compromisso
            if campo != "remarcacao" and valor not in (None, ""):
                base[campo] = valor

        return base

    pendente = estado.get("pendente") or {}

    # Duas vias para reconhecer uma remarcacao, porque uma so nao basta:
    #
    # - o agente marca `remarcacao` quando a propria mensagem diz que
    #   mudou ("na verdade e dia 25");
    # - o regex reconhece a confirmacao a uma pergunta que o assistente
    #   fez ("sim, foi remarcado"). Isso foi tentado por prompt e falhou:
    #   com o bloco do historico junto, o modelo respondia false.
    confirmou = confirma_remarcacao(estado.get("mensagem")) if pendente else None
    remarcou = bool(extracao.get("remarcacao")) or confirmou is True

    base = dict(anterior)

    # Remarcacao confirmada: aplica o dado que ficou esperando desde o
    # conflito. "sim, foi remarcado" nao repete a data nova, entao sem
    # isto nao haveria o que aplicar.
    if remarcou and pendente:
        base = aplicar(base, pendente)

    conflitos = [
        campo
        for campo in CAMPOS_EXCLUDENTES
        if base.get(campo)
        and extracao.get(campo)
        and str(base[campo]).strip().lower() != str(extracao[campo]).strip().lower()
    ]

    # Contradicao sem remarcacao declarada: nao funde, pergunta. A
    # extracao fica guardada em `pendente`, a espera da confirmacao.
    if conflitos and not remarcou:
        return {"conflitos": conflitos, "pendente": extracao}

    fundido = aplicar(base, extracao)
    fundido["classificacao"] = "cuidado"

    return {
        "compromisso": fundido,
        "conflitos": [],
        "pendente": None,
        "encerrado": False,
    }


def perguntar_conflito(estado: EstadoGrupo) -> dict:
    """A mensagem nova contradiz o combinado: pergunta, nao decide.

    Resposta deterministica, sem LLM. O compromisso acumulado fica como
    estava: nada e sobrescrito ate alguem do grupo esclarecer.
    """
    anterior = estado.get("compromisso") or {}
    extracao = estado.get("extracao") or {}

    divergencias = "; ".join(
        f"{campo}: antes {anterior.get(campo)}, agora {extracao.get(campo)}"
        for campo in estado.get("conflitos", [])
    )

    return {"resposta": prompts.RESPOSTA_CONFLITO.format(divergencias=divergencias)}


def encerrar(estado: EstadoGrupo) -> dict:
    """Marca o compromisso como fechado quando nao falta mais nada.

    Fechado nao significa agendado: nada foi gravado em agenda nenhuma.
    Significa que a proxima mensagem do grupo comeca um compromisso novo
    em vez de continuar somando neste.

    O responsavel entra na conta junto com os campos obrigatorios. Ele
    nao e obrigatorio para o compromisso existir, mas o assistente acabou
    de perguntar quem acompanha - encerrar antes da resposta chegar faria
    o "eu levo ela" seguinte cair num compromisso novo e vazio.
    """
    compromisso = estado.get("compromisso") or {}

    completo = not faltantes(compromisso) and bool(compromisso.get("responsavel"))

    return {"encerrado": completo}


# ---------------------------------------------------------------------------
# Agente 2 e seu guardrail
# ---------------------------------------------------------------------------


def coordenar(estado: EstadoGrupo) -> dict:
    """Agente 2: transforma o compromisso em resposta ao grupo.

    Recebe apenas o JSON validado, nunca a mensagem original. Assim ele nao
    pode reintroduzir um detalhe que o agente 1 descartou.
    """
    # `classificacao` fica de fora: quem decide o caminho e o grafo, nao o
    # agente. Se o campo chegasse ate aqui, o agente acabaria citando o
    # valor dentro da mensagem ao grupo ("a classificacao e cuidado"), que
    # e jargao interno do sistema.
    dados = {
        campo: valor
        for campo, valor in (estado.get("compromisso") or {}).items()
        if campo != "classificacao"
    }

    # Duas datas, de proposito: a tool exige AAAA-MM-DD e o texto ao grupo
    # precisa dela por extenso. Converter era regra de prompt e a LLM
    # errava o dia; agora ela so copia a que serve a cada uso.
    if dados.get("data"):
        dados["data_por_extenso"] = data_por_extenso(dados["data"])

    pedido = prompts.PROMPT_COORDENAR.format(
        compromisso=json.dumps(dados, ensure_ascii=False, indent=2)
    )

    texto, gravacao = _conversar_com_agenda(
        coordenador.PERSONA,
        pedido,
        resposta_anterior=estado.get("resposta_bruta"),
        erro=estado.get("erro_resposta"),
    )

    return {
        "resposta_bruta": texto,
        "gravacao": gravacao,
        "tentativas_resposta": estado.get("tentativas_resposta", 0) + 1,
    }


def validar_resposta(estado: EstadoGrupo) -> dict:
    """Guardrail do agente 2. Codigo deterministico, sem LLM.

    A resposta so pode afirmar que gravou se a tool tiver confirmado - e
    quem diz isso e o `gravacao` no estado, nao a LLM (CLAUDE.md, secao 4).
    """
    aprovado, saida = checar_resposta(
        estado.get("resposta_bruta") or "", bool(estado.get("gravacao"))
    )

    if not aprovado:
        return {"erro_resposta": saida, "resposta": None}

    return {"erro_resposta": None, "resposta": saida}


# ---------------------------------------------------------------------------
# Comandos de consulta
# ---------------------------------------------------------------------------


def responder_compromisso(estado: EstadoGrupo) -> dict:
    """Comando !compromisso: mostra o que esta combinado. Sem LLM.

    Duas partes: o compromisso que o grupo ainda esta montando, que mora no
    estado, e os ja gravados na agenda, que moram no banco. O primeiro some
    quando o thread e apagado; o segundo fica.
    """
    aberto = None if estado.get("encerrado") else estado.get("compromisso")

    partes = [resumir(aberto)]

    try:
        gravados = resumir_gravados(listar_ativos())
    except Exception as erro:
        print("falha ao ler a agenda:", type(erro).__name__, flush=True)
        gravados = "Nao foi possivel consultar a agenda agora."

    if gravados:
        partes.append(gravados)

    return {"resposta": "\n\n".join(partes)}


def responder_andamento(estado: EstadoGrupo) -> dict:
    """Comando !andamento: responde uma pergunta do grupo.

    Le o compromisso acumulado e as ultimas falas. Nao altera nada: quem
    pergunta nao esta combinando compromisso.
    """
    aberto = None if estado.get("encerrado") else estado.get("compromisso")

    # Sem compromisso nao ha o que a LLM possa responder sem inventar
    if not aberto:
        return {"resposta": prompts.RESPOSTA_SEM_COMPROMISSO}

    dados = {campo: valor for campo, valor in aberto.items() if campo != "classificacao"}

    if dados.get("data"):
        dados["data"] = data_por_extenso(dados["data"])

    pedido = prompts.PROMPT_ANDAMENTO.format(
        pergunta=estado["mensagem"],
        compromisso=json.dumps(dados, ensure_ascii=False, indent=2),
    )

    historico = estado.get("historico") or []

    if historico:
        pedido += prompts.HISTORICO.format(
            conversa="\n".join(f"{f['quem']}: {f['texto']}" for f in historico)
        )

    texto = _conversar(
        coordenador.PERSONA,
        pedido,
        resposta_anterior=estado.get("resposta_bruta"),
        erro=estado.get("erro_resposta"),
    )

    return {
        "resposta_bruta": texto,
        "tentativas_resposta": estado.get("tentativas_resposta", 0) + 1,
    }


def validar_andamento(estado: EstadoGrupo) -> dict:
    """Guardrail da resposta a uma pergunta. Sem LLM.

    Reprova resposta vazia, afirmacao de agendamento e data ou horario
    citados quando o compromisso nao os tem.
    """
    # O no anterior pode ter respondido sem LLM, quando nao ha
    # compromisso: nesse caso nao ha nada bruto para validar.
    if not estado.get("resposta_bruta"):
        return {"erro_resposta": None}

    aberto = None if estado.get("encerrado") else estado.get("compromisso")

    aprovado, saida = checar_andamento(estado["resposta_bruta"], aberto)

    if not aprovado:
        return {"erro_resposta": saida, "resposta": None}

    return {"erro_resposta": None, "resposta": saida}


def falha_andamento(_estado: EstadoGrupo) -> dict:
    """O agente nao conseguiu responder dentro do limite de tentativas."""
    return {"resposta": prompts.RESPOSTA_FALHA_ANDAMENTO}


# ---------------------------------------------------------------------------
# Agente 3 e seu guardrail
# ---------------------------------------------------------------------------


def responder_duvida(estado: EstadoGrupo) -> dict:
    """Comando !duvida: o agente 3 responde pelo Guia do Cuidador.

    Unico agente com ferramenta: ele mesmo decide buscar no Guia antes de
    responder. Busca, indice e instrucoes em `app/agents/RAG.py`.

    O compromisso do grupo nao entra aqui de proposito. A pergunta e sobre
    cuidado, nao sobre o combinado - para isso existe o !andamento -, e
    assim nenhum dado de saude vai parar neste prompt (CLAUDE.md, secao 8).
    """
    pergunta = (estado.get("mensagem") or "").strip()

    if not pergunta:
        return {"resposta": prompts.RESPOSTA_SEM_PERGUNTA}

    # O agente e criado do zero a cada chamada: sem o motivo da reprovacao
    # junto, a reexecucao repetiria o mesmo erro no escuro.
    erro = estado.get("erro_resposta")

    if erro:
        pergunta = f"{pergunta}\n\n{prompts.PROMPT_CORRIGIR.format(erro=erro)}"

    try:
        texto = RAG.pergunta_ao_agente(pergunta)
    except Exception as falha:
        # Loga o tipo do erro, nunca a pergunta: ela e conteudo do grupo.
        print("falha ao consultar o Guia:", type(falha).__name__, flush=True)
        return {"resposta": prompts.RESPOSTA_FALHA_GUIA}

    return {
        "resposta_bruta": texto,
        "tentativas_resposta": estado.get("tentativas_resposta", 0) + 1,
    }


def validar_duvida(estado: EstadoGrupo) -> dict:
    """Guardrail do agente 3. Codigo deterministico, sem LLM.

    O agente decide consultar o Guia; este codigo decide se a resposta
    chega ao grupo. Sem pagina citada e sem admitir que nao sabe, nao
    chega - e nenhuma resposta pode indicar medicacao.
    """
    # Pergunta vazia ou consulta falhada ja respondem sem LLM: nesses
    # casos nao ha nada bruto para validar.
    if not estado.get("resposta_bruta"):
        return {"erro_resposta": None}

    aprovado, saida = checar_orientacao(estado["resposta_bruta"])

    if not aprovado:
        return {"erro_resposta": saida, "resposta": None}

    return {"erro_resposta": None, "resposta": saida}


def falha_duvida(_estado: EstadoGrupo) -> dict:
    """O agente 3 nao produziu resposta aprovada dentro do limite."""
    return {"resposta": prompts.RESPOSTA_FALHA_GUIA}


# ---------------------------------------------------------------------------
# Nos deterministicos de saida
# ---------------------------------------------------------------------------


def resposta_fixa(estado: EstadoGrupo) -> dict:
    """Mensagem que nao e de cuidado: responde sem chamar LLM.

    Nao ha resumo a fazer nem pergunta a formular, e o texto e sempre o
    mesmo. No CrewAI isso custava uma chamada de LLM inteira.
    """
    # Le a classificacao da extracao desta mensagem, nao do compromisso
    # acumulado: o que decide a resposta e o que ESTA mensagem foi.
    classificacao = (estado.get("extracao") or {}).get("classificacao")

    return {
        "resposta": prompts.RESPOSTA_FIXA.get(
            classificacao, prompts.RESPOSTA_FIXA["conversa"]
        )
    }


def falha_extracao(_estado: EstadoGrupo) -> dict:
    """O agente 1 esgotou as tentativas sem produzir JSON valido.

    A extracao fica nula de proposito: pedir que a pessoa reescreva e
    melhor do que seguir com um dado que nao passou na validacao. O
    compromisso acumulado nao e tocado - uma mensagem ilegivel nao apaga
    o que o grupo ja tinha combinado.
    """
    return {"extracao": None, "resposta": prompts.RESPOSTA_FALHA_EXTRACAO}


def limpar(estado: EstadoGrupo) -> dict:
    """Ultimo no de todos os caminhos: guarda a troca e descarta o resto.

    Guarda a mensagem e a resposta no historico, cortado nas ultimas
    MAX_HISTORICO falas. A resposta do assistente entra junto porque sem
    ela o agente nao tem como saber que uma fala curta ("sim, foi") esta
    respondendo a uma pergunta dele.

    Descarta o que nao e lido na proxima mensagem: `extracao_bruta` e
    `resposta_bruta` sao as saidas cruas da LLM, incluindo as reprovadas
    pelos guardrails, e nao servem para nada depois (CLAUDE.md, secao 8).

    `resposta` e `extracao` ficam: o `processar()` le os dois depois do
    invoke, para o retorno e para o log da rota.
    """
    historico = list(estado.get("historico") or [])

    mensagem = (estado.get("mensagem") or "").strip()
    resposta = (estado.get("resposta") or "").strip()

    if mensagem:
        historico.append(
            {"quem": estado.get("autor") or "alguem do grupo", "texto": mensagem}
        )

    if resposta:
        historico.append({"quem": "assistente", "texto": resposta})

    atualizacao = {"historico": historico[-MAX_HISTORICO:]}

    if not RETER_HISTORICO:
        atualizacao.update({"mensagem": "", "extracao_bruta": None, "resposta_bruta": None})

    return atualizacao


def falha_coordenacao(_estado: EstadoGrupo) -> dict:
    """O agente 2 esgotou as tentativas sem produzir resposta aprovada.

    O compromisso extraido continua valido e vai para a rota; so o texto ao
    grupo e substituido.
    """
    return {"resposta": prompts.RESPOSTA_FALHA_COORDENACAO}


# ---------------------------------------------------------------------------
# Arestas condicionais
# ---------------------------------------------------------------------------


def rumo_apos_extracao(estado: EstadoGrupo) -> str:
    """Para onde ir depois de validar a extracao.

    Tres saidas: repetir o agente 1, desistir, ou seguir pelo valor de
    `classificacao`. O roteamento acontece DEPOIS da extracao porque e ela
    que produz o campo que decide o caminho.
    """
    if estado.get("erro_extracao"):
        if estado.get("tentativas_extracao", 0) < MAX_TENTATIVAS:
            return "interpretar"
        return "falha_extracao"

    classificacao = (estado.get("extracao") or {}).get("classificacao")

    return "fundir" if classificacao == "cuidado" else "resposta_fixa"


def rumo_inicial(estado: EstadoGrupo) -> str:
    """Por onde a mensagem entra no grafo, pelo comando que o grupo usou.

    E o Roteador do desenho original, agora deterministico: o comando ja
    diz a intencao, entao nao ha o que uma LLM precise classificar aqui.
    """
    comando = (estado.get("comando") or "agenda").strip().lower()

    if comando == "compromisso":
        return "responder_compromisso"

    if comando == "andamento":
        return "responder_andamento"

    if comando == "duvida":
        return "responder_duvida"

    return "interpretar"


def rumo_apos_andamento(estado: EstadoGrupo) -> str:
    """Para onde ir depois de validar a resposta a uma pergunta."""
    if estado.get("erro_resposta"):
        if estado.get("tentativas_resposta", 0) < MAX_TENTATIVAS:
            return "responder_andamento"
        return "falha_andamento"

    return "limpar"


def rumo_apos_duvida(estado: EstadoGrupo) -> str:
    """Para onde ir depois de validar a resposta do agente 3."""
    if estado.get("erro_resposta"):
        if estado.get("tentativas_resposta", 0) < MAX_TENTATIVAS:
            return "responder_duvida"
        return "falha_duvida"

    return "limpar"


def rumo_apos_fusao(estado: EstadoGrupo) -> str:
    """Para onde ir depois de tentar fundir com o combinado anterior."""
    return "perguntar_conflito" if estado.get("conflitos") else "coordenar"


def rumo_apos_resposta(estado: EstadoGrupo) -> str:
    """Para onde ir depois de validar a resposta ao grupo."""
    if estado.get("erro_resposta"):
        if estado.get("tentativas_resposta", 0) < MAX_TENTATIVAS:
            return "coordenar"
        return "falha_coordenacao"

    return "encerrar"
