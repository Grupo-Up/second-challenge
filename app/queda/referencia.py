"""Modelo de referencia (baseline): estatisticas da janela + arvores.

Para que serve, se a rede do projeto e a LSTM:

1. E a regua. A LSTM so vale a pena se ganhar deste modelo simples no
   mesmo teste. Sem uma referencia, "93% de acuracia" nao diz nada.
2. Roda sem TensorFlow. Da para testar o ciclo inteiro (relogio -> API
   -> alerta no grupo) antes de a LSTM estar treinada, e os testes
   automaticos usam ele.

Nao e a rede neural do projeto e nao deve ser apresentado como tal.
"""

from __future__ import annotations

import numpy as np


def resumir(janelas: np.ndarray) -> np.ndarray:
    """(n, 125, 4) -> (n, 24): max, min, media, desvio, amplitude e maior
    variacao entre amostras seguidas, por canal."""
    x = np.asarray(janelas, dtype=np.float32)
    variacao = np.abs(np.diff(x, axis=1)).max(axis=1)
    partes = [
        x.max(axis=1),
        x.min(axis=1),
        x.mean(axis=1),
        x.std(axis=1),
        np.percentile(x, 95, axis=1) - np.percentile(x, 5, axis=1),
        variacao,
    ]
    return np.concatenate(partes, axis=1)


def treinar(janelas: np.ndarray, y: np.ndarray, semente: int = 42):
    from sklearn.ensemble import HistGradientBoostingClassifier

    modelo = HistGradientBoostingClassifier(
        max_iter=300, learning_rate=0.05, class_weight="balanced", random_state=semente
    )
    modelo.fit(resumir(janelas), y)
    return modelo


class ModeloReferencia:
    """Mesma interface do modelo Keras: prever(janelas) -> probabilidade."""

    tipo = "referencia"

    def __init__(self, modelo):
        self.modelo = modelo

    def prever(self, janelas: np.ndarray) -> np.ndarray:
        return self.modelo.predict_proba(resumir(janelas))[:, 1]
