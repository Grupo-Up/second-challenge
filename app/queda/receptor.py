"""Junta as amostras que chegam de cada relogio e avalia janela a janela.

O Sensor Logger manda os dados em lotes pequenos, a cada fracao de
segundo. Uma janela de 2,5 s precisa de varios lotes, entao cada relogio
tem um buffer com os ultimos segundos. A cada lote novo, as janelas que
terminaram desde a ultima avaliacao (uma a cada 0,5 s, como no treino)
passam pelo detector.

Fica so na memoria e so os ultimos segundos: o dado de movimento e dado
de saude (CLAUDE.md, secao 8) e nao precisa ser guardado para o alerta
funcionar. Reiniciar a API perde no maximo alguns segundos de buffer.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

import numpy as np

from app.queda import sinais

# Historico mantido: a janela + 1 s para estimar a gravidade + folga
HISTORICO_S = sinais.JANELA_S + sinais.GRAVIDADE_S + 1.5
# Se o relogio ficar mais que isso sem mandar nada, o buffer recomeca:
# interpolar por cima de um buraco inventaria movimento que nao houve
BURACO_S = 1.0
# Depois de um alerta, o mesmo relogio nao alerta de novo por um tempo.
# Uma queda gera varias janelas acima do limiar; o grupo recebe uma mensagem.
INTERVALO_ENTRE_ALERTAS_S = 60.0


@dataclass
class Avaliacao:
    probabilidade: float
    janelas_avaliadas: int
    alertar: bool


@dataclass
class _Buffer:
    t: list = field(default_factory=list)
    acel: list = field(default_factory=list)
    giro: list = field(default_factory=list)
    ultimo_fim_avaliado: float = -np.inf
    ultimo_alerta: float = -np.inf


class Receptor:
    def __init__(self, detector, relogio=time.monotonic):
        self.detector = detector
        self._buffers: dict[str, _Buffer] = {}
        self._trava = threading.Lock()
        self._agora = relogio

    def receber(self, dispositivo: str, t, acel, giro) -> Avaliacao:
        """`t` em segundos, `acel` total em m/s2 e `giro` em rad/s (relogio.py)."""
        t = np.asarray(t, dtype=float)
        if len(t) == 0:
            return Avaliacao(0.0, 0, False)

        with self._trava:
            buf = self._buffers.setdefault(dispositivo, _Buffer())

            if buf.t and t.min() - buf.t[-1] > BURACO_S:
                ultimo_alerta = buf.ultimo_alerta
                buf = self._buffers[dispositivo] = _Buffer(ultimo_alerta=ultimo_alerta)

            buf.t.extend(t.tolist())
            buf.acel.extend(np.asarray(acel, dtype=float).tolist())
            buf.giro.extend(np.asarray(giro, dtype=float).tolist())

            ordem = np.argsort(buf.t, kind="stable")
            tt = np.asarray(buf.t)[ordem]
            aa = np.asarray(buf.acel)[ordem]
            gg = np.asarray(buf.giro)[ordem]

            manter = tt >= tt[-1] - HISTORICO_S
            buf.t, buf.acel, buf.giro = tt[manter].tolist(), aa[manter].tolist(), gg[manter].tolist()

            janelas, fins = self._janelas_novas(buf)
            if len(janelas) == 0:
                return Avaliacao(0.0, 0, False)

            buf.ultimo_fim_avaliado = float(fins[-1])
            prob = float(np.max(self.detector.prever(janelas)))

            agora = self._agora()
            alertar = (
                prob >= self.detector.limiar
                and agora - buf.ultimo_alerta >= INTERVALO_ENTRE_ALERTAS_S
            )
            if alertar:
                buf.ultimo_alerta = agora
            return Avaliacao(prob, len(janelas), alertar)

    @staticmethod
    def _janelas_novas(buf: _Buffer):
        t = np.asarray(buf.t)
        grade = sinais.grade_comum(t, t)
        if len(grade) < sinais.AMOSTRAS_JANELA + sinais.AMOSTRAS_GRAVIDADE:
            return [], []

        s = sinais.calcular_sinais(
            sinais.reamostrar(t, np.asarray(buf.acel), grade),
            sinais.reamostrar(t, np.asarray(buf.giro), grade),
        )
        # So janelas com 1 s de historico antes, para a gravidade estimada
        # ja ter estabilizado, e que terminaram depois da ultima avaliada
        inicios = np.arange(
            len(s) - sinais.AMOSTRAS_JANELA, sinais.AMOSTRAS_GRAVIDADE - 1, -sinais.AMOSTRAS_PASSO
        )[::-1]
        fins = grade[inicios + sinais.AMOSTRAS_JANELA - 1]
        # Uma janela a cada 0,5 s, como no treino: lotes que chegam mais
        # rapido nao aumentam o numero de avaliacoes (nem de alarmes falsos)
        novas = fins >= buf.ultimo_fim_avaliado + sinais.PASSO_S - 1e-3
        inicios, fins = inicios[novas], fins[novas]
        if len(inicios) == 0:
            return [], []
        return np.stack([s[i : i + sinais.AMOSTRAS_JANELA] for i in inicios]), fins

    def esquecer(self, dispositivo: str) -> None:
        with self._trava:
            self._buffers.pop(dispositivo, None)
