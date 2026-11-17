
"""A tool de agenda do agente 2.

Vinda da branch `agente_tool`, onde era uma BaseTool do CrewAI. Aqui e uma
@tool do LangChain: o `args_schema` virou os parametros da funcao e as
conexoes passam pelo `banco.py`. As quatro acoes e as validacoes sao as
mesmas.

O agente nao recebe SQL: ele escolhe uma das acoes e passa os campos. Toda
escrita e verificada aqui antes de ir ao banco, porque quem preenche os
argumentos e uma LLM e ela pode inventar um valor para completar a chamada
(CLAUDE.md, secao 5).
"""

from datetime import date
from typing import Any, Optional

from langchain_core.tools import tool

from app.compromisso import FORMATO_DATA, FORMATO_HORARIO, hoje
from app.tools.banco import ajustar, conectar

CAMPOS = (
    "id", "tipo", "pessoa_idosa", "especialidade", "data",
    "horario", "local", "responsavel", "status",
)

OBRIGATORIOS_AGENDA = ("tipo", "pessoa_idosa", "data", "horario")

# Fora dos obrigatorios do compromisso, gravar exige responsavel. Sem
# alguem que aceitou acompanhar, o compromisso ainda nao esta combinado -
# e o sistema nao escolhe quem leva a pessoa idosa (CLAUDE.md, secao 6).
SEM_RESPONSAVEL = (
    "sem responsavel confirmado: ninguem do grupo aceitou acompanhar. "
    "Pergunte ao grupo quem pode acompanhar antes de gravar"
)


def _validar(data: Optional[str], horario: Optional[str]) -> None:
    """Formato e data no passado. Levanta ValueError, que a tool devolve
    como texto ao agente em vez de gravar."""
    if data is not None:
        if not FORMATO_DATA.match(data):
            raise ValueError("data deve estar no formato AAAA-MM-DD")

        try:
            if date.fromisoformat(data) < hoje():
                raise ValueError("nao e permitido usar uma data passada")
        except ValueError as erro:
            if "passada" in str(erro):
                raise
            raise ValueError("data inexistente no calendario") from erro

    if horario is not None and not FORMATO_HORARIO.match(horario):
        raise ValueError("horario deve estar no formato HH:MM")


def _faltando(**campos) -> list[str]:
    return [nome for nome, valor in campos.items() if not valor]


def _linha(valores: tuple[Any, ...]) -> str:
    return ", ".join(str(valor) for valor in valores)


def listar_ativos() -> list[dict]:
    """Compromissos ativos, em dicionario. Sem LLM e sem @tool: e o que o
    comando !compromisso usa para mostrar o que ja foi gravado.

    Ordenado por id, nao por data: a lista mostra o numero de cada um, e
    ver #2 antes de #1 parece defeito. A ordem cronologica fica para a
    acao `consultar`, que e o agente quem le.
    """
    with conectar() as conexao:
        linhas = conexao.execute(
            ajustar(
                f"SELECT {', '.join(CAMPOS)} FROM compromissos "
                "WHERE status = 'ativo' ORDER BY id"
            )
        ).fetchall()

    return [dict(zip(CAMPOS, linha)) for linha in linhas]


@tool
def agenda(
    acao: str,
    compromisso_id: Optional[int] = None,
    tipo: Optional[str] = None,
    pessoa_idosa: Optional[str] = None,
    especialidade: Optional[str] = None,
    data: Optional[str] = None,
    horario: Optional[str] = None,
    local: Optional[str] = None,
    responsavel: Optional[str] = None,
) -> str:
    """Consulta e altera compromissos de cuidado na agenda.

    Use apenas para compromissos ja confirmados pelo grupo e com todos os
    dados presentes. Nunca invente valores ausentes.

    acao: criar, consultar, alterar ou deletar.
    compromisso_id: obrigatorio em alterar e deletar.
    data: AAAA-MM-DD. horario: HH:MM.
    """
    try:
        if acao == "criar":
            return _criar(tipo, pessoa_idosa, especialidade, data, horario, local, responsavel)

        if acao == "consultar":
            return _consultar(compromisso_id, data, pessoa_idosa)

        if acao == "alterar":
            return _alterar(
                compromisso_id, tipo, pessoa_idosa, especialidade,
                data, horario, local, responsavel,
            )

        if acao == "deletar":
            return _deletar(compromisso_id)
    except ValueError as erro:
        return f"Falha na operacao da agenda: {erro}"
    except Exception as erro:
        # Nao vaza a mensagem do banco: pode trazer o conteudo da linha.
        return f"Falha na operacao da agenda: {type(erro).__name__}"

    return "Acao invalida. Use criar, consultar, alterar ou deletar."


def _criar(tipo, pessoa_idosa, especialidade, data, horario, local, responsavel) -> str:
    ausentes = _faltando(
        tipo=tipo, pessoa_idosa=pessoa_idosa, data=data, horario=horario
    )

    if ausentes:
        raise ValueError("campos obrigatorios ausentes: " + ", ".join(ausentes))

    if not responsavel:
        raise ValueError(SEM_RESPONSAVEL)

    _validar(data, horario)

    with conectar() as conexao:
        existente = conexao.execute(
            ajustar(
                "SELECT id FROM compromissos WHERE status = 'ativo' "
                "AND tipo = ? AND pessoa_idosa = ? AND data = ? AND horario = ? "
                "LIMIT 1"
            ),
            (tipo, pessoa_idosa, data, horario),
        ).fetchone()

        if existente:
            return f"Compromisso ativo ja existe com id {existente[0]}."

        criado = conexao.execute(
            ajustar(
                "INSERT INTO compromissos "
                "(tipo, pessoa_idosa, especialidade, data, horario, local, responsavel) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "RETURNING id, tipo, pessoa_idosa, data, horario, status"
            ),
            (tipo, pessoa_idosa, especialidade, data, horario, local, responsavel),
        ).fetchone()

    return f"Compromisso criado: {_linha(criado)}"


def _consultar(compromisso_id, data, pessoa_idosa) -> str:
    _validar(data, None)

    filtros = ["status = 'ativo'"]
    valores: list[Any] = []

    for coluna, valor in (
        ("id", compromisso_id), ("data", data), ("pessoa_idosa", pessoa_idosa)
    ):
        if valor is not None:
            filtros.append(f"{coluna} = ?")
            valores.append(valor)

    with conectar() as conexao:
        linhas = conexao.execute(
            ajustar(
                f"SELECT {', '.join(CAMPOS)} FROM compromissos "
                f"WHERE {' AND '.join(filtros)} ORDER BY data, horario, id"
            ),
            valores,
        ).fetchall()

    if not linhas:
        return "Nenhum compromisso ativo encontrado."

    return "Compromissos encontrados:\n" + "\n".join(_linha(linha) for linha in linhas)


def _alterar(compromisso_id, tipo, pessoa_idosa, especialidade, data, horario, local, responsavel) -> str:
    if compromisso_id is None:
        raise ValueError("compromisso_id e obrigatorio para alterar")

    ausentes = _faltando(
        tipo=tipo, pessoa_idosa=pessoa_idosa, data=data, horario=horario
    )

    if ausentes:
        raise ValueError("campos obrigatorios ausentes: " + ", ".join(ausentes))

    if not responsavel:
        raise ValueError(SEM_RESPONSAVEL)

    _validar(data, horario)

    with conectar() as conexao:
        alterado = conexao.execute(
            ajustar(
                "UPDATE compromissos SET tipo = ?, pessoa_idosa = ?, "
                "especialidade = ?, data = ?, horario = ?, local = ?, "
                "responsavel = ?, atualizado_em = CURRENT_TIMESTAMP "
                "WHERE id = ? AND status = 'ativo' "
                "RETURNING id, tipo, pessoa_idosa, data, horario, status"
            ),
            (tipo, pessoa_idosa, especialidade, data, horario, local,
             responsavel, compromisso_id),
        ).fetchone()

    if alterado is None:
        return f"Compromisso ativo nao encontrado: id {compromisso_id}."

    return f"Compromisso alterado: {_linha(alterado)}"


def _deletar(compromisso_id) -> str:
    if compromisso_id is None:
        raise ValueError("compromisso_id e obrigatorio para deletar")

    # Cancelar em vez de apagar: o historico do que a familia combinou nao
    # some porque alguem errou o id.
    with conectar() as conexao:
        cancelado = conexao.execute(
            ajustar(
                "UPDATE compromissos SET status = 'cancelado', "
                "atualizado_em = CURRENT_TIMESTAMP "
                "WHERE id = ? AND status = 'ativo' "
                "RETURNING id, tipo, pessoa_idosa, data, horario, status"
            ),
            (compromisso_id,),
        ).fetchone()

    if cancelado is None:
        return f"Compromisso ativo nao encontrado: id {compromisso_id}."

    return f"Compromisso deletado: {_linha(cancelado)}"
