"""Metricas do detector de quedas, usadas no notebook e nos testes.

Acuracia nao serve aqui: com ~7% de janelas de queda, um modelo que
nunca alerta ja acerta 93%. As metricas que importam para a familia:

- recall de quedas (por gravacao): de cada 100 quedas, quantas geraram
  alerta. E a principal: perder uma queda e o erro grave.
- alarmes falsos por hora de atividade normal: quantas vezes o grupo
  receberia um alerta sem queda. Medido a parte nos idosos, que sao o
  publico do projeto.
- precisao e recall por janela, para acompanhar o treino.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.queda.sinais import PASSO_S


def por_janela(y: np.ndarray, p: np.ndarray, limiar: float) -> dict:
    pred = p >= limiar
    vp = int(np.sum(pred & (y == 1)))
    fp = int(np.sum(pred & (y == 0)))
    fn = int(np.sum(~pred & (y == 1)))
    precisao = vp / (vp + fp) if vp + fp else 0.0
    recall = vp / (vp + fn) if vp + fn else 0.0
    f1 = 2 * precisao * recall / (precisao + recall) if precisao + recall else 0.0
    return {"precisao_janela": precisao, "recall_janela": recall, "f1_janela": f1}


def _episodios(alertas: np.ndarray) -> int:
    """Janelas seguidas acima do limiar contam como UM alerta, como na API
    (que espera um intervalo antes de alertar de novo o mesmo relogio)."""
    alertas = np.asarray(alertas, dtype=bool)
    if alertas.size == 0:
        return 0
    return int(alertas[0]) + int(np.sum(alertas[1:] & ~alertas[:-1]))


def por_evento(info: pd.DataFrame, y: np.ndarray, p: np.ndarray, limiar: float) -> dict:
    """Metricas que a familia sentiria. `info` vem de dados.montar()."""
    tabela = info.reset_index(drop=True).assign(y=y, alerta=p >= limiar)
    eh_queda = tabela["classe"].str.upper().str.startswith("F")

    quedas = tabela[eh_queda & (tabela["y"] == 1)].groupby("gravacao")["alerta"].any()
    recall_evento = float(quedas.mean()) if len(quedas) else float("nan")

    def falsos_por_hora(parte: pd.DataFrame) -> float:
        if parte.empty:
            return float("nan")
        episodios = sum(_episodios(g["alerta"].to_numpy()) for _, g in parte.groupby("gravacao"))
        horas = len(parte) * PASSO_S / 3600
        return episodios / horas

    atividades = tabela[~eh_queda]
    return {
        "recall_quedas": recall_evento,
        "quedas_avaliadas": int(len(quedas)),
        "alarmes_falsos_por_hora": falsos_por_hora(atividades),
        "alarmes_falsos_por_hora_idosos": falsos_por_hora(atividades[atividades["idoso"]]),
        "horas_de_atividade": len(atividades) * PASSO_S / 3600,
    }


def escolher_limiar(
    info: pd.DataFrame, y: np.ndarray, p: np.ndarray, recall_minimo: float = 0.95
) -> float:
    """Maior limiar que ainda detecta >= recall_minimo das quedas.

    Escolhido na VALIDACAO, nunca no teste: escolher no teste e ajustar a
    prova depois de ver as respostas. Quanto maior o limiar, menos alarmes
    falsos; o recall minimo e o piso que a equipe aceita perder.
    """
    for limiar in np.round(np.arange(0.95, 0.04, -0.05), 2):
        if por_evento(info, y, p, limiar)["recall_quedas"] >= recall_minimo:
            return float(limiar)
    return 0.05


def resumo(info: pd.DataFrame, y: np.ndarray, p: np.ndarray, limiar: float) -> dict:
    return {"limiar": limiar, **por_janela(y, p, limiar), **por_evento(info, y, p, limiar)}
