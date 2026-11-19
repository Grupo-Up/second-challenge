"""Transforma leituras de acelerometro e giroscopio em janelas para a rede.

Este arquivo e usado em DOIS lugares, e precisa ser o mesmo nos dois:

    1. no treino (notebook do Colab), sobre o dataset WEDA-FALL e sobre
       as gravacoes do Apple Watch feitas com o Sensor Logger;
    2. na API, sobre os dados que chegam do relogio em tempo real.

Se o treino e a API calcularem os sinais de jeitos diferentes, a rede
recebe em producao algo que nunca viu, e o resultado do teste deixa de
valer. Por isso nada de pre-processamento fica espalhado pelo notebook.

Decisoes, com o motivo de cada uma:

- Reamostragem para 50 Hz. No WEDA as quedas foram gravadas a ~40 Hz e
  as atividades do dia a dia a ~50 Hz. Sem reamostrar, a rede pode
  aprender a frequencia de gravacao em vez da queda. O Apple Watch grava
  a 50, 100 ou 200 Hz, conforme a configuracao do Sensor Logger.

- Quatro sinais que nao dependem de como o relogio esta no pulso:
      |a|   modulo da aceleracao (m/s2)
      |w|   modulo da velocidade angular (rad/s)
      a_v   aceleracao na direcao da gravidade (m/s2)
      a_h   aceleracao no plano horizontal (m/s2)
  O WEDA foi gravado com outro relogio, com eixos e pulso diferentes dos
  do Apple Watch. Os eixos x, y, z de um nao correspondem aos do outro;
  os modulos e a projecao na gravidade, sim. Quaternions de orientacao e
  a "vertical_accel" do WEDA ficaram de fora: o referencial muda de
  aparelho para aparelho e os idosos do WEDA nem tem vertical_accel.

- Gravidade estimada com media movel CAUSAL de 1 s (so olha o passado).
  Em tempo real nao existe o futuro; se o treino usasse media centrada,
  a API calcularia outro sinal.

- Limites de saturacao: o acelerometro do WEDA satura perto de 64 m/s2.
  O do Apple Watch vai mais longe. Cortar os dois no mesmo valor evita
  que a rede veja em producao picos que nunca viu no treino.
"""

from __future__ import annotations

import numpy as np

FREQ_HZ = 50
JANELA_S = 2.5
PASSO_S = 0.5
GRAVIDADE_S = 1.0

AMOSTRAS_JANELA = int(round(JANELA_S * FREQ_HZ))  # 125
AMOSTRAS_PASSO = int(round(PASSO_S * FREQ_HZ))  # 25
AMOSTRAS_GRAVIDADE = int(round(GRAVIDADE_S * FREQ_HZ))  # 50

G = 9.80665
LIMITE_ACEL = 60.0  # m/s2, um pouco abaixo da saturacao do WEDA
LIMITE_GIRO = 30.0  # rad/s

CANAIS = ("acel_modulo", "giro_modulo", "acel_vertical", "acel_horizontal")


def reamostrar(t: np.ndarray, valores: np.ndarray, t_novo: np.ndarray) -> np.ndarray:
    """Interpola cada coluna de `valores` nos instantes `t_novo`.

    Se a gravacao original for bem mais rapida que 50 Hz (100 ou 200 Hz
    do Apple Watch), faz antes uma media simples de tamanho
    `freq_original / 50`. Sem isso, a reamostragem pega um ponto a cada
    tantos e um pico curto pode cair entre dois pontos.
    """
    t = np.asarray(t, dtype=float)
    valores = np.asarray(valores, dtype=float)
    if valores.ndim == 1:
        valores = valores[:, None]

    ordem = np.argsort(t, kind="stable")
    t, valores = t[ordem], valores[ordem]
    t, unicos = np.unique(t, return_index=True)
    valores = valores[unicos]

    if len(t) >= 2:
        freq_original = (len(t) - 1) / max(t[-1] - t[0], 1e-9)
        largura = int(round(freq_original / FREQ_HZ))
        if largura >= 2:
            nucleo = np.ones(largura) / largura
            valores = np.column_stack(
                [np.convolve(valores[:, i], nucleo, mode="same") for i in range(valores.shape[1])]
            )

    return np.column_stack(
        [np.interp(t_novo, t, valores[:, i]) for i in range(valores.shape[1])]
    )


def grade_comum(t_acel: np.ndarray, t_giro: np.ndarray) -> np.ndarray:
    """Instantes a 50 Hz no trecho em que os dois sensores tem dados."""
    inicio = max(np.min(t_acel), np.min(t_giro))
    fim = min(np.max(t_acel), np.max(t_giro))
    if fim <= inicio:
        return np.empty(0)
    n = int(np.floor((fim - inicio) * FREQ_HZ)) + 1
    return inicio + np.arange(n) / FREQ_HZ


def media_causal(x: np.ndarray, n: int) -> np.ndarray:
    """Media das ultimas `n` linhas, linha a linha. No inicio usa o que tem."""
    soma = np.cumsum(x, axis=0)
    saida = np.empty_like(soma)
    k = min(n, len(x))
    saida[:k] = soma[:k] / np.arange(1, k + 1)[:, None]
    if len(x) > n:
        saida[n:] = (soma[n:] - soma[:-n]) / n
    return saida


def calcular_sinais(acel: np.ndarray, giro: np.ndarray) -> np.ndarray:
    """Recebe aceleracao total (m/s2, COM gravidade) e giroscopio (rad/s),
    ja reamostrados a 50 Hz, e devolve a matriz (n, 4) dos CANAIS."""
    acel = np.asarray(acel, dtype=float)
    giro = np.asarray(giro, dtype=float)

    acel_modulo = np.linalg.norm(acel, axis=1)
    giro_modulo = np.linalg.norm(giro, axis=1)

    gravidade = media_causal(acel, AMOSTRAS_GRAVIDADE)
    direcao = gravidade / np.maximum(np.linalg.norm(gravidade, axis=1, keepdims=True), 1e-6)
    acel_vertical = np.sum(acel * direcao, axis=1)
    acel_horizontal = np.sqrt(np.maximum(acel_modulo**2 - acel_vertical**2, 0.0))

    sinais = np.column_stack([acel_modulo, giro_modulo, acel_vertical, acel_horizontal])
    sinais[:, 0] = np.clip(sinais[:, 0], 0, LIMITE_ACEL)
    sinais[:, 1] = np.clip(sinais[:, 1], 0, LIMITE_GIRO)
    sinais[:, 2] = np.clip(sinais[:, 2], -LIMITE_ACEL, LIMITE_ACEL)
    sinais[:, 3] = np.clip(sinais[:, 3], 0, LIMITE_ACEL)
    return sinais.astype(np.float32)


def preparar_gravacao(
    t_acel: np.ndarray, acel: np.ndarray, t_giro: np.ndarray, giro: np.ndarray
) -> np.ndarray:
    """Do dado cru (tempos em segundos, unidades SI) ate a matriz de sinais."""
    t = grade_comum(np.asarray(t_acel), np.asarray(t_giro))
    if len(t) == 0:
        return np.empty((0, len(CANAIS)), dtype=np.float32)
    return calcular_sinais(reamostrar(t_acel, acel, t), reamostrar(t_giro, giro, t))


def janelas(sinais: np.ndarray, passo: int = AMOSTRAS_PASSO) -> tuple[np.ndarray, np.ndarray]:
    """Corta em janelas de 2,5 s. Devolve (janelas, indice_de_inicio)."""
    if len(sinais) < AMOSTRAS_JANELA:
        return np.empty((0, AMOSTRAS_JANELA, sinais.shape[1]), np.float32), np.empty(0, int)
    inicios = np.arange(0, len(sinais) - AMOSTRAS_JANELA + 1, passo)
    return np.stack([sinais[i : i + AMOSTRAS_JANELA] for i in inicios]), inicios


def rotular_queda(sinais: np.ndarray, inicios: np.ndarray) -> np.ndarray:
    """Rotulo das janelas de uma gravacao de QUEDA.

    O impacto e o pico de |a|. A janela vale 1 se o impacto cai na parte
    central dela (nem nos primeiros nem nos ultimos 0,5 s), e -1 nas
    demais: antes da queda a pessoa so estava andando ou parada, e depois
    esta deitada. Essas janelas sao ambiguas e saem do treino (-1), em
    vez de virarem "queda" e ensinarem que ficar parado e cair.
    """
    impacto = int(np.argmax(sinais[:, 0]))
    margem = AMOSTRAS_PASSO
    rotulos = np.full(len(inicios), -1, dtype=int)
    dentro = (impacto >= inicios + margem) & (impacto < inicios + AMOSTRAS_JANELA - margem)
    rotulos[dentro] = 1
    return rotulos


def padronizar(x: np.ndarray, media: np.ndarray, desvio: np.ndarray) -> np.ndarray:
    """Media e desvio vem SO do treino e ficam salvos na configuracao."""
    return ((x - media) / np.maximum(desvio, 1e-6)).astype(np.float32)
