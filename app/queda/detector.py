"""Carrega o modelo treinado no Colab e responde: qual a chance de queda?

O notebook exporta uma pasta com dois arquivos, que vao para
`modelos/queda/` na raiz do projeto (ou para QUEDA_MODELO_DIR):

    config_queda.json    tipo do modelo, media e desvio do treino,
                         limiar escolhido na validacao, metricas do teste
    modelo_queda.keras   a LSTM (ou modelo_queda.joblib, a referencia)

A configuracao guarda a frequencia, a janela e os canais com que o
modelo foi treinado. Se nao baterem com os de `sinais.py`, o detector
se recusa a carregar: um modelo treinado com outro pre-processamento
responderia qualquer coisa, sem dar erro nenhum.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from app.queda import sinais

PASTA_PADRAO = Path(__file__).resolve().parents[2] / "modelos" / "queda"


class ModeloIncompativel(RuntimeError):
    pass


@dataclass
class DetectorQueda:
    modelo: object
    limiar: float
    tipo: str
    media: np.ndarray | None = None
    desvio: np.ndarray | None = None
    versao: str = "sem-versao"
    metricas: dict = field(default_factory=dict)

    def prever(self, janelas: np.ndarray) -> np.ndarray:
        """(n, 125, 4) -> probabilidade de queda de cada janela, entre 0 e 1."""
        janelas = np.asarray(janelas, dtype=np.float32)
        if janelas.ndim == 2:
            janelas = janelas[None]
        if len(janelas) == 0:
            return np.empty(0)
        if self.tipo == "lstm":
            x = sinais.padronizar(janelas, self.media, self.desvio)
            return np.asarray(self.modelo.predict(x, verbose=0)).reshape(-1)
        return np.asarray(self.modelo.prever(janelas)).reshape(-1)


def _conferir(config: dict) -> None:
    esperado = {
        "freq_hz": sinais.FREQ_HZ,
        "janela_s": sinais.JANELA_S,
        "canais": list(sinais.CANAIS),
    }
    for chave, valor in esperado.items():
        if config.get(chave) != valor:
            raise ModeloIncompativel(
                f"modelo treinado com {chave}={config.get(chave)!r}, "
                f"mas sinais.py usa {valor!r}. Treine de novo com o sinais.py atual."
            )


def carregar(pasta: str | Path | None = None) -> DetectorQueda:
    pasta = Path(pasta or os.environ.get("QUEDA_MODELO_DIR") or PASTA_PADRAO)
    caminho_config = pasta / "config_queda.json"
    if not caminho_config.exists():
        raise FileNotFoundError(
            f"sem modelo de queda em {pasta}. Rode o notebook de treino e copie a pasta exportada."
        )
    config = json.loads(caminho_config.read_text(encoding="utf-8"))
    _conferir(config)

    tipo = config["tipo"]
    arquivo = pasta / config["arquivo"]
    if tipo == "lstm":
        # Importado so aqui: a API sobe sem TensorFlow se o modelo for a
        # referencia, e o TensorFlow leva segundos para carregar.
        import tensorflow as tf

        modelo = tf.keras.models.load_model(arquivo)
    elif tipo == "referencia":
        import joblib

        from app.queda.referencia import ModeloReferencia

        modelo = ModeloReferencia(joblib.load(arquivo))
    else:
        raise ModeloIncompativel(f"tipo de modelo desconhecido: {tipo!r}")

    return DetectorQueda(
        modelo=modelo,
        limiar=float(config["limiar"]),
        tipo=tipo,
        media=np.asarray(config["media"], dtype=np.float32) if config.get("media") else None,
        desvio=np.asarray(config["desvio"], dtype=np.float32) if config.get("desvio") else None,
        versao=config.get("versao", "sem-versao"),
        metricas=config.get("metricas", {}),
    )
