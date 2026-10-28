
"""O estado do agente: um compromisso pendente por grupo.

E o que transforma o sistema de reflexo simples em reflexo baseado em
modelo. Sem isso, "eu levo ela" nao tem a que se referir.

Nesta etapa o armazenamento e um dicionario em memoria. As duas funcoes de
acesso -- carregar_pendente e salvar_pendente -- sao a unica porta: trocar
por SQLite depois mexe so neste arquivo.

LIMITE CONHECIDO: o dicionario vive no processo. Com uvicorn --workers
maior que 1, cada worker teria o seu, e mensagens do mesmo grupo cairiam em
processos diferentes. Rode com um worker ate o SQLite entrar.
"""

import hashlib
import threading
from datetime import date, datetime, timedelta

from compromisso import FUSO, hoje

# Pendente sem resposta por mais tempo que isso e descartado.
# Combinacao de cuidado que ninguem retomou em dois dias provavelmente
# morreu na conversa -- e dado de saude nao fica guardado por garantia
# (CLAUDE.md, secao 8).
VALIDADE = timedelta(hours=48)

# chave -> {"compromisso": dict, "salvo_em": datetime}
_PENDENTES = {}

# Um lock por grupo, segurado durante o processar() inteiro: grupos
# diferentes seguem em paralelo, o mesmo grupo fica serial.
_LOCKS = {}
_LOCK_DOS_LOCKS = threading.Lock()


def chave(grupo_id):
    """Identificador derivado do grupo.

    O JID do WhatsApp nao e guardado: o que fica e o hash. O armazenamento
    contem dados de saude e vai para disco quando virar SQLite -- nao
    precisa levar junto o identificador da conversa (CLAUDE.md, secao 8).
    """
    return hashlib.sha256(str(grupo_id).encode()).hexdigest()[:32]


def trava(grupo_id):
    """Lock do grupo. Use como context manager em volta do processar().

    O perigo nao e o dicionario -- dict do CPython ja e atomico. E a janela
    de alguns segundos entre carregar e salvar, que atravessa duas chamadas
    de LLM: dois pedidos do mesmo grupo em paralelo leriam o mesmo pendente
    e o segundo a salvar apagaria a fusao do primeiro.
    """
    k = chave(grupo_id)

    with _LOCK_DOS_LOCKS:
        return _LOCKS.setdefault(k, threading.Lock())


def _vencido(registro):
    """Regra unica de descarte por tempo, aplicada na leitura."""
    if datetime.now(FUSO) - registro["salvo_em"] > VALIDADE:
        return True

    data = registro["compromisso"].get("data")

    if data:
        try:
            if date.fromisoformat(data) < hoje():
                return True
        except (ValueError, TypeError):
            # Data corrompida no armazenamento: joga fora em vez de
            # arrastar para a proxima mensagem
            return True

    return False


def carregar_pendente(grupo_id):
    """O compromisso pendente do grupo, ou None.

    O descarte acontece aqui, na leitura, e nao na escrita: a passagem do
    tempo e o unico evento que ninguem dispara. Um pendente valido ontem
    venceu hoje sem que nada tenha acontecido.
    """
    if grupo_id is None:
        return None

    k = chave(grupo_id)
    registro = _PENDENTES.get(k)

    if registro is None:
        return None

    if _vencido(registro):
        _PENDENTES.pop(k, None)
        return None

    # Copia: quem chamar nao mexe no que esta guardado
    return dict(registro["compromisso"])


def salvar_pendente(grupo_id, compromisso):
    """Guarda o pendente do grupo. compromisso=None apaga."""
    if grupo_id is None:
        return

    k = chave(grupo_id)

    if compromisso is None:
        _PENDENTES.pop(k, None)
        return

    _PENDENTES[k] = {
        "compromisso": dict(compromisso),
        "salvo_em": datetime.now(FUSO),
    }


def esquecer_tudo():
    """Limpa o estado. Usada pelos testes, nao pelo fluxo normal."""
    _PENDENTES.clear()
