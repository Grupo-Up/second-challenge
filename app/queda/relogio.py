"""Le o que o Sensor Logger manda do Apple Watch e converte para SI.

O sensor do relogio no Sensor Logger se chama "Wrist Motion" e, segundo a
referencia de unidades do proprio app (awesome-sensor-logger, UNITS.md):

    rotationRateX/Y/Z     rad/s
    gravityX/Y/Z          g por padrao; m/s2 se "Standardise Units &
    accelerationX/Y/Z     Frames" estiver ligado
    quaternionW/X/Y/Z     sem unidade (nao usamos)
    time                  nanossegundos desde a epoca (1970)

`acceleration` e a aceleracao do usuario, SEM a gravidade (como o
userAcceleration do Core Motion). O WEDA usa a aceleracao total, entao a
total e reconstruida aqui: total = acceleration + gravity.

A unidade nao e confiada a configuracao do app: e detectada pelo modulo
da gravidade, que em repouso ou em movimento fica perto de 1 se estiver
em g e perto de 9,8 se estiver em m/s2. Assim um integrante do grupo que
ligar a opcao sem avisar nao quebra o detector.
"""

from __future__ import annotations

from typing import Iterable, Mapping

import numpy as np

from app.queda.sinais import G

EIXOS = ("X", "Y", "Z")


def _coluna(linha: Mapping, nomes: Iterable[str]) -> float:
    for nome in nomes:
        if nome in linha and linha[nome] is not None:
            return float(linha[nome])
    raise KeyError(f"nenhuma das colunas {list(nomes)} na amostra")


def _tempo_em_segundos(valor: float) -> float:
    """O app manda nanossegundos; o simulador e o CSV podem mandar segundos."""
    valor = float(valor)
    if valor > 1e15:  # nanossegundos desde 1970
        return valor / 1e9
    if valor > 1e12:  # milissegundos
        return valor / 1e3
    return valor


def fator_unidade(gravidade: np.ndarray) -> float:
    """1.0 se ja estiver em m/s2, 9,80665 se estiver em g."""
    modulo = float(np.median(np.linalg.norm(gravidade, axis=1)))
    return 1.0 if modulo > 4.0 else G


def converter_amostras(amostras: list[Mapping]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Lista de amostras do Wrist Motion -> (t em s, aceleracao total m/s2, giro rad/s).

    Cada amostra e um dicionario com `time` e as colunas acima, como sai
    de uma linha do WristMotion.csv ou de um item do streaming HTTP.
    """
    if not amostras:
        vazio = np.empty((0, 3))
        return np.empty(0), vazio, vazio

    t = np.array([_tempo_em_segundos(a["time"]) for a in amostras])
    gravidade = np.array([[_coluna(a, [f"gravity{e}"]) for e in EIXOS] for a in amostras])
    usuario = np.array([[_coluna(a, [f"acceleration{e}"]) for e in EIXOS] for a in amostras])
    # O nome da coluna de rotacao mudou entre versoes da documentacao
    giro = np.array(
        [[_coluna(a, [f"rotationRate{e}", f"rotation{e}"]) for e in EIXOS] for a in amostras]
    )

    fator = fator_unidade(gravidade)
    acel_total = (usuario + gravidade) * fator
    return t, acel_total, giro
