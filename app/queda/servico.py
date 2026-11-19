"""O que a API faz quando chega um lote do relogio.

Separado das rotas do FastAPI para poder ser testado sem subir a API:
as rotas em app/routes/sensor.py so chamam as funcoes daqui.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from app.queda import alertas, detector as detector_mod, relogio
from app.queda.receptor import Receptor

_estado: dict[str, Any] = {"detector": None, "receptor": None, "erro": None}

# Com QUEDA_CAPTURA=1 o corpo cru de cada lote vai para dados/capturas/.
# So para a equipe descobrir o formato exato que o Sensor Logger manda.
# Desligado por padrao: e dado de saude (CLAUDE.md, secao 8).
PASTA_CAPTURAS = Path(__file__).resolve().parents[2] / "dados" / "capturas"


def iniciar(pasta=None, detector=None) -> None:
    """Chamado quando a API sobe. Sem modelo, a API sobe do mesmo jeito:
    so o detector de quedas fica desligado, e /sensor responde 503."""
    try:
        detector = detector or detector_mod.carregar(pasta)
    except Exception as erro:  # noqa: BLE001 - qualquer falha so desliga o detector
        _estado.update(detector=None, receptor=None, erro=f"{type(erro).__name__}: {erro}")
        print("detector de quedas desligado:", _estado["erro"], flush=True)
        return
    _estado.update(detector=detector, receptor=Receptor(detector), erro=None)
    print(
        "detector de quedas carregado:",
        detector.tipo,
        detector.versao,
        "| limiar",
        detector.limiar,
        flush=True,
    )


def situacao() -> dict:
    d = _estado["detector"]
    if d is None:
        return {"ativo": False, "motivo": _estado["erro"]}
    return {"ativo": True, "tipo": d.tipo, "versao": d.versao, "limiar": d.limiar, "metricas": d.metricas}


def extrair_amostras(corpo: Any) -> tuple[str | None, list[dict]]:
    """Tira do lote o identificador do aparelho e as amostras do Wrist Motion.

    Formato esperado do streaming HTTP do Sensor Logger:

        {"messageId": 3, "sessionId": "...", "deviceId": "...",
         "payload": [{"name": "wristmotion", "time": 1732050000000000000,
                      "values": {"gravityX": ..., "accelerationX": ...,
                                 "rotationRateX": ..., ...}}, ...]}

    A leitura e tolerante (lista direta, valores fora de "values", nome
    com outra grafia) porque o formato exato deve ser conferido com
    QUEDA_CAPTURA=1 antes da demonstracao. Itens de outros sensores
    (GPS, bateria, celular) sao ignorados.
    """
    dispositivo = None
    itens = corpo
    if isinstance(corpo, dict):
        dispositivo = corpo.get("deviceId") or corpo.get("dispositivo")
        itens = corpo.get("payload", [])
    amostras = []
    for item in itens or []:
        if not isinstance(item, dict):
            continue
        nome = str(item.get("name", "wristmotion")).lower().replace("_", "").replace(" ", "")
        if "wrist" not in nome:
            continue
        valores = dict(item.get("values") or {})
        for chave, valor in item.items():
            if chave not in ("name", "values"):
                valores.setdefault(chave, valor)
        if "time" in valores:
            amostras.append(valores)
    return dispositivo, amostras


def capturar(corpo: Any) -> Path | None:
    if os.environ.get("QUEDA_CAPTURA") != "1":
        return None
    PASTA_CAPTURAS.mkdir(parents=True, exist_ok=True)
    arquivo = PASTA_CAPTURAS / f"lote_{datetime.now():%Y%m%d_%H%M%S_%f}.json"
    arquivo.write_text(json.dumps(corpo, ensure_ascii=False), encoding="utf-8")
    return arquivo


def processar_lote(corpo: Any, dispositivo: str | None = None) -> tuple[int, dict]:
    """Devolve (codigo HTTP, resposta). Nunca devolve o dado do sensor."""
    capturar(corpo)
    receptor: Receptor | None = _estado["receptor"]
    if receptor is None:
        return 503, {"erro": "detector de quedas desligado", "motivo": _estado["erro"]}

    do_corpo, amostras = extrair_amostras(corpo)
    dispositivo = dispositivo or do_corpo
    if not dispositivo:
        return 422, {"erro": "lote sem identificador do relogio (deviceId ou ?dispositivo=)"}
    if not amostras:
        return 200, {"amostras": 0, "aviso": "nenhuma amostra de Wrist Motion no lote"}

    try:
        t, acel, giro = relogio.converter_amostras(amostras)
    except (KeyError, ValueError) as erro:
        return 422, {"erro": f"amostra fora do formato esperado: {erro}"}

    avaliacao = receptor.receber(dispositivo, t, acel, giro)
    resposta = {
        "amostras": len(amostras),
        "janelas_avaliadas": avaliacao.janelas_avaliadas,
        "probabilidade": round(avaliacao.probabilidade, 4),
        "alerta": None,
    }
    if avaliacao.alertar:
        detector = _estado["detector"]
        alerta = alertas.registrar(dispositivo, avaliacao.probabilidade, detector.versao)
        resposta["alerta"] = alerta["id"] if alerta else "relogio sem grupo vinculado"
        # So metadados no log: nada do sinal, nem nome da pessoa
        print(
            "queda suspeita | alerta:",
            resposta["alerta"],
            "| probabilidade:",
            resposta["probabilidade"],
            flush=True,
        )
    return 200, resposta
