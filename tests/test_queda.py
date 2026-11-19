"""Testes do detector de quedas. Rodam sem TensorFlow e sem o dataset.

    pytest tests/test_queda.py -v

Os sinais sao sinteticos de proposito: o que se testa aqui e o encanamento
(unidades, janelas, buffer, alertas, banco), nao a qualidade do modelo.
A qualidade e medida no notebook, com o conjunto de teste.
"""

import json
import time

import numpy as np
import pytest

from app.queda import alertas, avaliacao, detector, relogio, servico, sinais
from app.queda.receptor import INTERVALO_ENTRE_ALERTAS_S, Receptor


# --------------------------------------------------------------- utilidades
def gravacao_sintetica(duracao=6.0, freq=100, impacto_em=None, seed=0):
    """Pulso parado/andando devagar; com `impacto_em`, um pico de queda."""
    rng = np.random.default_rng(seed)
    t = np.arange(0, duracao, 1 / freq)
    acel = np.tile([0.0, 0.0, sinais.G], (len(t), 1)) + rng.normal(0, 0.3, (len(t), 3))
    giro = rng.normal(0, 0.2, (len(t), 3))
    if impacto_em is not None:
        perto = np.abs(t - impacto_em) < 0.05
        acel[perto] += [30.0, 10.0, 25.0]
        giro[perto] += [8.0, 3.0, 5.0]
    return t, acel, giro


class DetectorFalso:
    """Queda = pico de |a| acima de 30 m/s2 na janela."""

    limiar = 0.5
    tipo = "falso"
    versao = "teste"
    metricas = {}

    def __init__(self):
        self.chamadas = 0

    def prever(self, janelas):
        self.chamadas += len(janelas)
        return (np.asarray(janelas)[:, :, 0].max(axis=1) > 30).astype(float)


def em_amostras_sensorlogger(t, acel, giro, inicio_ns=1_732_000_000_000_000_000, em_g=True):
    gravidade = sinais.media_causal(acel, 50)
    usuario = acel - gravidade
    fator = sinais.G if em_g else 1.0
    return [
        {
            "time": inicio_ns + int(ti * 1e9),
            **{f"gravity{e}": gr[i] / fator for i, e in enumerate("XYZ")},
            **{f"acceleration{e}": us[i] / fator for i, e in enumerate("XYZ")},
            **{f"rotationRate{e}": gi[i] for i, e in enumerate("XYZ")},
        }
        for ti, gr, us, gi in zip(t, gravidade, usuario, giro)
    ]


# ------------------------------------------------------------------ sinais
def test_reamostra_para_50hz():
    t, acel, giro = gravacao_sintetica(duracao=4, freq=200)
    s = sinais.preparar_gravacao(t, acel, t, giro)
    assert s.shape[1] == len(sinais.CANAIS)
    assert abs(len(s) - 4 * sinais.FREQ_HZ) <= 1


def test_sinais_nao_dependem_da_posicao_do_relogio():
    """Girar o relogio no pulso (outro aparelho, outro braco) nao muda os
    4 sinais: e isso que permite treinar com o WEDA e usar no Apple Watch."""
    t, acel, giro = gravacao_sintetica(impacto_em=3.0)
    angulo = 1.1
    rot = np.array(
        [[np.cos(angulo), -np.sin(angulo), 0], [np.sin(angulo), np.cos(angulo), 0], [0, 0, 1]]
    ) @ np.array([[1, 0, 0], [0, np.cos(0.7), -np.sin(0.7)], [0, np.sin(0.7), np.cos(0.7)]])
    original = sinais.preparar_gravacao(t, acel, t, giro)
    girado = sinais.preparar_gravacao(t, acel @ rot.T, t, giro @ rot.T)
    np.testing.assert_allclose(original, girado, atol=1e-3)


def test_parado_tem_aceleracao_vertical_igual_a_gravidade():
    t, acel, giro = gravacao_sintetica()
    s = sinais.preparar_gravacao(t, acel, t, giro)
    assert abs(np.median(s[:, 2]) - sinais.G) < 0.2
    assert np.median(s[:, 3]) < 1.0


def test_janelas_e_rotulo_da_queda():
    t, acel, giro = gravacao_sintetica(duracao=8, impacto_em=4.0)
    s = sinais.preparar_gravacao(t, acel, t, giro)
    jan, inicios = sinais.janelas(s)
    assert jan.shape[1:] == (sinais.AMOSTRAS_JANELA, len(sinais.CANAIS))
    rotulos = sinais.rotular_queda(s, inicios)
    # impacto no centro de ~3 janelas (1,5 s de 0,5 em 0,5 s); o resto e ambiguo
    assert 2 <= (rotulos == 1).sum() <= 4
    assert set(np.unique(rotulos)) <= {-1, 1}


# ----------------------------------------------------------------- relogio
@pytest.mark.parametrize("em_g", [True, False])
def test_unidade_do_sensor_logger_e_detectada(em_g):
    t, acel, giro = gravacao_sintetica()
    amostras = em_amostras_sensorlogger(t, acel, giro, em_g=em_g)
    t2, acel2, giro2 = relogio.converter_amostras(amostras)
    np.testing.assert_allclose(acel2, acel, atol=1e-6)
    np.testing.assert_allclose(giro2, giro, atol=1e-9)
    np.testing.assert_allclose(t2 - t2[0], t - t[0], atol=1e-6)


def test_aceita_rotation_sem_rate():
    amostra = {
        "time": 1.0,
        "gravityX": 0, "gravityY": 0, "gravityZ": -1,
        "accelerationX": 0, "accelerationY": 0, "accelerationZ": 0,
        "rotationX": 0.1, "rotationY": 0.2, "rotationZ": 0.3,
    }
    _, acel, giro = relogio.converter_amostras([amostra])
    np.testing.assert_allclose(giro[0], [0.1, 0.2, 0.3])
    assert abs(np.linalg.norm(acel[0]) - sinais.G) < 1e-6


# ---------------------------------------------------------------- receptor
def enviar_em_lotes(receptor, dispositivo, t, acel, giro, lote_s=0.2, desloca=0.0):
    resultados = []
    inicio = 0
    while inicio < len(t):
        fim = max(int(np.searchsorted(t, t[inicio] + lote_s)), inicio + 1)
        resultados.append(
            receptor.receber(dispositivo, t[inicio:fim] + desloca, acel[inicio:fim], giro[inicio:fim])
        )
        inicio = fim
    return resultados


def test_receptor_alerta_uma_vez_por_queda():
    det = DetectorFalso()
    receptor = Receptor(det)
    resultados = enviar_em_lotes(receptor, "r1", *gravacao_sintetica(duracao=8, impacto_em=5.0))
    assert sum(r.alertar for r in resultados) == 1
    assert max(r.probabilidade for r in resultados) == 1.0


def test_receptor_sem_queda_nao_alerta():
    receptor = Receptor(DetectorFalso())
    resultados = enviar_em_lotes(receptor, "r1", *gravacao_sintetica(duracao=10))
    assert not any(r.alertar for r in resultados)


def test_receptor_avalia_uma_janela_a_cada_meio_segundo():
    """Lotes de 0,1 s nao podem gerar 5x mais avaliacoes que no treino."""
    det = DetectorFalso()
    enviar_em_lotes(Receptor(det), "r1", *gravacao_sintetica(duracao=10), lote_s=0.1)
    esperado = (10 - sinais.JANELA_S - sinais.GRAVIDADE_S) / sinais.PASSO_S
    assert abs(det.chamadas - esperado) <= 3


def test_intervalo_entre_alertas_e_por_relogio():
    agora = [0.0]
    receptor = Receptor(DetectorFalso(), relogio=lambda: agora[0])
    t, acel, giro = gravacao_sintetica(duracao=8, impacto_em=5.0)
    assert sum(r.alertar for r in enviar_em_lotes(receptor, "r1", t, acel, giro)) == 1
    # Outra queda logo depois, no mesmo relogio: ainda no intervalo
    assert not any(r.alertar for r in enviar_em_lotes(receptor, "r1", t, acel, giro, desloca=8))
    # Outro relogio alerta normalmente
    assert sum(r.alertar for r in enviar_em_lotes(receptor, "r2", t, acel, giro)) == 1
    # Passado o intervalo, o primeiro volta a alertar
    agora[0] += INTERVALO_ENTRE_ALERTAS_S + 1
    assert sum(r.alertar for r in enviar_em_lotes(receptor, "r1", t, acel, giro, desloca=16)) == 1


def test_buraco_no_streaming_recomeca_o_buffer():
    det = DetectorFalso()
    receptor = Receptor(det)
    t, acel, giro = gravacao_sintetica(duracao=3)
    enviar_em_lotes(receptor, "r1", t, acel, giro)
    antes = det.chamadas
    # 1 s de dado depois de 10 s sem nada: pouco demais para uma janela
    enviar_em_lotes(receptor, "r1", t[:100], acel[:100], giro[:100], desloca=13)
    assert det.chamadas == antes


# ---------------------------------------------------- servico, banco e bot
@pytest.fixture
def servico_ativo(banco_temporario):
    servico.iniciar(detector=DetectorFalso())
    yield
    servico._estado.update(detector=None, receptor=None, erro=None)


def lote(t, acel, giro, dispositivo="relogio-1"):
    amostras = em_amostras_sensorlogger(t, acel, giro)
    return {
        "messageId": 1,
        "deviceId": dispositivo,
        "payload": [{"name": "wristmotion", "time": a["time"], "values": a} for a in amostras]
        + [{"name": "battery", "time": amostras[0]["time"], "values": {"batteryLevel": 0.8}}],
    }


def test_sem_modelo_responde_503(banco_temporario):
    servico._estado.update(detector=None, receptor=None, erro="sem modelo")
    codigo, _ = servico.processar_lote({"deviceId": "x", "payload": []})
    assert codigo == 503


def test_lote_sem_dispositivo_e_recusado(servico_ativo):
    codigo, _ = servico.processar_lote({"payload": []})
    assert codigo == 422


def test_queda_sem_vinculo_nao_vira_alerta(servico_ativo):
    codigo, resposta = servico.processar_lote(lote(*gravacao_sintetica(duracao=8, impacto_em=5)))
    assert codigo == 200
    assert resposta["alerta"] == "relogio sem grupo vinculado"
    assert alertas.pendentes() == []


def test_ciclo_completo_do_alerta(servico_ativo):
    alertas.vincular("relogio-1", "123@g.us", "Helena")
    _, resposta = servico.processar_lote(lote(*gravacao_sintetica(duracao=8, impacto_em=5)))
    assert isinstance(resposta["alerta"], int)
    assert "time" not in json.dumps(resposta)  # o sinal nunca volta na resposta

    pendentes = alertas.pendentes()
    assert [(a["grupo"], a["pessoa_idosa"], a["status"]) for a in pendentes] == [
        ("123@g.us", "Helena", "pendente")
    ]
    assert pendentes[0]["criado_em"].endswith("Z")

    # Antes de enviado, o grupo nao viu o alerta: nao ha o que responder
    assert alertas.registrar_retorno("123@g.us", foi_queda=False) is None
    assert alertas.marcar_enviado(pendentes[0]["id"])
    assert not alertas.marcar_enviado(pendentes[0]["id"])  # nao envia duas vezes
    assert alertas.pendentes() == []

    assert alertas.registrar_retorno("123@g.us", foi_queda=False)["status"] == "falso"
    assert alertas.resumo_retornos()["falso"] == 1
    assert alertas.registrar_retorno("outro@g.us", foi_queda=True) is None


def test_extrai_so_o_wrist_motion():
    _, amostras = servico.extrair_amostras(
        {"deviceId": "d", "payload": [
            {"name": "wristMotion", "time": 1, "values": {"gravityX": 0}},
            {"name": "location", "time": 1, "values": {"latitude": -23}},
        ]}
    )
    assert len(amostras) == 1 and "latitude" not in amostras[0]


def test_captura_desligada_por_padrao(monkeypatch, tmp_path):
    monkeypatch.delenv("QUEDA_CAPTURA", raising=False)
    monkeypatch.setattr(servico, "PASTA_CAPTURAS", tmp_path)
    servico.capturar({"x": 1})
    assert list(tmp_path.iterdir()) == []


# ------------------------------------------------------ detector e metricas
def test_modelo_com_outro_preprocessamento_nao_carrega(tmp_path):
    (tmp_path / "config_queda.json").write_text(
        json.dumps({"tipo": "referencia", "arquivo": "x", "freq_hz": 40, "janela_s": 2.5,
                    "canais": list(sinais.CANAIS), "limiar": 0.5})
    )
    with pytest.raises(detector.ModeloIncompativel):
        detector.carregar(tmp_path)


def test_exporta_e_carrega_a_referencia(tmp_path):
    pytest.importorskip("sklearn")
    from app.queda import exportar, referencia

    x_queda, x_normal = [], []
    for seed in range(30):  # o modelo exige 20 exemplos por folha
        s = sinais.preparar_gravacao(*_tac(gravacao_sintetica(duracao=4, impacto_em=2.0, seed=seed)))
        x_queda.append(sinais.janelas(s)[0][1])
        s = sinais.preparar_gravacao(*_tac(gravacao_sintetica(duracao=4, seed=100 + seed)))
        x_normal.append(sinais.janelas(s)[0][1])
    x = np.stack(x_queda + x_normal)
    y = np.array([1] * 30 + [0] * 30)
    modelo = referencia.treinar(x, y)
    exportar.salvar(tmp_path, tipo="referencia", modelo=modelo, limiar=0.5, metricas={"recall_quedas": 1.0})

    carregado = detector.carregar(tmp_path)
    p = carregado.prever(x)
    assert p[:30].mean() > 0.9 and p[30:].mean() < 0.1


def _tac(trio):
    t, acel, giro = trio
    return t, acel, t, giro


def test_metricas_por_evento():
    import pandas as pd

    info = pd.DataFrame(
        {
            "gravacao": ["q1", "q1", "q2", "d1", "d1", "d1"],
            "classe": ["F01", "F01", "F02", "D01", "D01", "D01"],
            "idoso": [False, False, False, True, True, True],
        }
    )
    y = np.array([1, 1, 1, 0, 0, 0])
    p = np.array([0.9, 0.2, 0.1, 0.8, 0.8, 0.1])
    m = avaliacao.por_evento(info, y, p, 0.5)
    assert m["recall_quedas"] == 0.5  # q1 detectada, q2 nao
    # d1: duas janelas seguidas acima = 1 alarme, em 3 x 0,5 s de atividade
    assert m["alarmes_falsos_por_hora_idosos"] == pytest.approx(1 / (3 * 0.5 / 3600))


# ------------------------------------------------------------------- rotas
def test_rotas_exigem_token(servico_ativo, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.routes import sensor

    app = FastAPI()
    app.include_router(sensor.router)
    cliente = TestClient(app)

    monkeypatch.setenv("QUEDA_TOKEN", "segredo")
    assert cliente.get("/alertas/pendentes").status_code == 401
    assert cliente.get("/alertas/pendentes?token=segredo").status_code == 200
    resposta = cliente.post(
        "/dispositivos",
        json={"dispositivo": "relogio-1", "grupo": "1@g.us", "pessoa_idosa": "Helena"},
        headers={"Authorization": "Bearer segredo"},
    )
    assert resposta.status_code == 200
    resposta = cliente.post(
        "/sensor/sensorlogger?token=segredo",
        json=lote(*gravacao_sintetica(duracao=8, impacto_em=5)),
    )
    assert resposta.status_code == 200 and isinstance(resposta.json()["alerta"], int)
