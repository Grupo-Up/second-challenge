"""Salva o modelo treinado no formato que o detector.py le.

Usado no fim do notebook (LSTM) e no scripts/treinar_referencia.py.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.queda import sinais


def salvar(
    pasta: str | Path,
    *,
    tipo: str,
    modelo,
    limiar: float,
    metricas: dict,
    media=None,
    desvio=None,
    versao: str | None = None,
    ambiente: dict | None = None,
) -> Path:
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)

    if tipo == "lstm":
        arquivo = "modelo_queda.keras"
        modelo.save(str(pasta / arquivo))
    elif tipo == "referencia":
        import joblib

        arquivo = "modelo_queda.joblib"
        joblib.dump(modelo, pasta / arquivo)
    else:
        raise ValueError(f"tipo desconhecido: {tipo!r}")

    agora = datetime.now(timezone.utc)
    config = {
        "tipo": tipo,
        "arquivo": arquivo,
        "versao": versao or f"{tipo}-{agora:%Y%m%d-%H%M}",
        "treinado_em": agora.isoformat(timespec="seconds"),
        "freq_hz": sinais.FREQ_HZ,
        "janela_s": sinais.JANELA_S,
        "canais": list(sinais.CANAIS),
        "limiar": float(limiar),
        "media": [float(v) for v in media] if media is not None else None,
        "desvio": [float(v) for v in desvio] if desvio is not None else None,
        "metricas": {k: (float(v) if isinstance(v, (int, float)) else v) for k, v in metricas.items()},
        # Versoes de bibliotecas do treino: o .keras so abre com um
        # TensorFlow/Keras da mesma versao principal na API
        "ambiente": ambiente or {},
    }
    (pasta / "config_queda.json").write_text(
        json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return pasta
