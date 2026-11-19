"""Faz o papel do Apple Watch: manda uma gravacao para a API em tempo real.

Le uma gravacao do WEDA (ou um WristMotion.csv exportado do Sensor
Logger), converte para o mesmo formato do streaming HTTP do Sensor
Logger e envia em lotes, no ritmo real. E como ensaiar a demonstracao
sem ninguem precisar cair.

    # uma queda de um usuario do TESTE (nunca visto no treino):
    python -m scripts.simular_relogio app/rede-neural/dataset/F01/U03_R01_accel.csv

    # uma caminhada, que NAO deve gerar alerta:
    python -m scripts.simular_relogio app/rede-neural/dataset/D01/U03_R01_accel.csv

    # uma gravacao real do relogio de voces:
    python -m scripts.simular_relogio gravacoes_apple_watch/F01_U40_R01/WristMotion.csv

Opcoes: --api (padrao http://localhost:8000), --dispositivo, --token,
--rapido (sem esperar o tempo real).

So usa a biblioteca padrao + numpy/pandas.
"""

import argparse
import json
import time
import urllib.error
import urllib.request

import numpy as np
import pandas as pd

from app.queda import sinais

LOTE_S = 0.2


def carregar(caminho: str) -> list[dict]:
    """Devolve amostras no formato do Wrist Motion do Sensor Logger (em g)."""
    if caminho.endswith("WristMotion.csv"):
        return pd.read_csv(caminho).to_dict("records")

    # WEDA: aceleracao total em m/s2 e giro em rad/s. O Sensor Logger
    # manda gravidade e aceleracao do usuario separadas, em g: separa aqui.
    base = caminho[: -len("_accel.csv")]
    acel = pd.read_csv(caminho)
    giro = pd.read_csv(base + "_gyro.csv")
    t = acel.iloc[:, 0].to_numpy(float)
    a = acel.iloc[:, 1:4].to_numpy(float)
    g = np.column_stack([np.interp(t, giro.iloc[:, 0], giro.iloc[:, i]) for i in (1, 2, 3)])
    gravidade = sinais.media_causal(a, int(sinais.GRAVIDADE_S * 50))
    usuario = a - gravidade
    inicio_ns = time.time_ns()
    return [
        {
            "time": inicio_ns + int(ti * 1e9),
            "gravityX": gr[0] / sinais.G,
            "gravityY": gr[1] / sinais.G,
            "gravityZ": gr[2] / sinais.G,
            "accelerationX": us[0] / sinais.G,
            "accelerationY": us[1] / sinais.G,
            "accelerationZ": us[2] / sinais.G,
            "rotationRateX": gi[0],
            "rotationRateY": gi[1],
            "rotationRateZ": gi[2],
        }
        for ti, gr, us, gi in zip(t, gravidade, usuario, g)
    ]


def enviar(api: str, token: str | None, corpo: dict) -> dict:
    url = f"{api.rstrip('/')}/sensor/sensorlogger"
    cabecalhos = {"Content-Type": "application/json"}
    if token:
        cabecalhos["Authorization"] = f"Bearer {token}"
    pedido = urllib.request.Request(url, json.dumps(corpo).encode(), cabecalhos, method="POST")
    try:
        with urllib.request.urlopen(pedido, timeout=10) as resposta:
            return json.loads(resposta.read())
    except urllib.error.HTTPError as erro:
        return {"erro_http": erro.code, "detalhe": erro.read().decode(errors="replace")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gravacao")
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--dispositivo", default="relogio-demo")
    parser.add_argument("--token", default=None)
    parser.add_argument("--rapido", action="store_true")
    args = parser.parse_args()

    amostras = carregar(args.gravacao)
    t = np.array([float(a["time"]) for a in amostras])
    t = (t - t[0]) / (1e9 if t[0] > 1e15 else 1)

    maior, lote_id, inicio = 0.0, 0, 0
    while inicio < len(amostras):
        fim = int(np.searchsorted(t, t[inicio] + LOTE_S))
        fim = max(fim, inicio + 1)
        corpo = {
            "messageId": lote_id,
            "sessionId": "simulacao",
            "deviceId": args.dispositivo,
            "payload": [
                {"name": "wristmotion", "time": a["time"], "values": a} for a in amostras[inicio:fim]
            ],
        }
        resposta = enviar(args.api, args.token, corpo)
        if "erro_http" in resposta:
            print(resposta)
            return
        maior = max(maior, resposta.get("probabilidade") or 0.0)
        if resposta.get("alerta"):
            print(f"t={t[inicio]:5.1f}s  ALERTA: {resposta['alerta']}  p={resposta['probabilidade']}")
        inicio, lote_id = fim, lote_id + 1
        if not args.rapido:
            time.sleep(LOTE_S)

    print(f"fim da gravacao | maior probabilidade de queda: {maior:.3f}")


if __name__ == "__main__":
    main()
