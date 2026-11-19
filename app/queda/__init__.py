"""Detector de quedas: Apple Watch -> rede neural -> alerta no grupo.

    sinais.py    pre-processamento, o MESMO no treino e na API
    relogio.py   converte o Wrist Motion do Sensor Logger para SI
    dados.py     monta o dataset de treino (WEDA + Apple Watch)
    detector.py  carrega o modelo treinado e da a probabilidade de queda
    receptor.py  junta as amostras de cada relogio e avalia janela a janela
    alertas.py   grava os alertas e o retorno da familia no banco

Visao geral e passo a passo em docs/QUEDA.md.
"""
