"""Treina o modelo de REFERENCIA (nao e a LSTM) e exporta para modelos/queda/.

Para que serve: testar o ciclo inteiro (relogio -> API -> alerta no
WhatsApp) sem TensorFlow e sem esperar o treino da LSTM no Colab.
Leva poucos segundos. Quando a LSTM estiver treinada, a pasta exportada
pelo notebook substitui esta.

    python -m scripts.treinar_referencia
    python -m scripts.treinar_referencia --apple-watch gravacoes_apple_watch

Roda a partir da raiz do projeto.
"""

import argparse
import json

import numpy as np

from app.queda import avaliacao, dados, exportar, referencia
from app.queda.detector import PASTA_PADRAO


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weda", default="app/rede-neural/dataset")
    parser.add_argument("--apple-watch", default=None, help="pasta com as gravacoes do Sensor Logger")
    parser.add_argument("--saida", default=str(PASTA_PADRAO))
    parser.add_argument("--recall-minimo", type=float, default=0.95)
    args = parser.parse_args()

    gravacoes = dados.listar_weda(args.weda)
    if args.apple_watch:
        gravacoes += dados.listar_apple_watch(args.apple_watch)
    x, y, info = dados.montar(gravacoes)
    parte = dados.separar(info).to_numpy()
    print(f"{len(gravacoes)} gravacoes, {len(x)} janelas, {int(y.sum())} de queda")

    treino, validacao, teste = (parte == p for p in ("treino", "validacao", "teste"))
    modelo = referencia.treinar(x[treino], y[treino])
    envoltorio = referencia.ModeloReferencia(modelo)

    p_val = envoltorio.prever(x[validacao])
    limiar = avaliacao.escolher_limiar(info[validacao], y[validacao], p_val, args.recall_minimo)
    p_teste = envoltorio.prever(x[teste])
    metricas = avaliacao.resumo(info[teste], y[teste], p_teste, limiar)
    print(json.dumps(metricas, indent=2, ensure_ascii=False))

    exportar.salvar(args.saida, tipo="referencia", modelo=modelo, limiar=limiar, metricas=metricas)
    print("exportado para", args.saida)


if __name__ == "__main__":
    np.seterr(all="ignore")
    main()
