"""Monta o dataset de treino: WEDA-FALL + gravacoes do Apple Watch.

Usado pelo notebook de treino. A API nao importa este arquivo (ele usa
pandas, que a API nao precisa).

Correcoes em relacao ao `app/rede-neural/extracao.py` antigo:

1. A gravacao e identificada por classe + usuario + repeticao
   ("F01/U01_R01"). O identificador antigo, "U01_R01", se repete nas 19
   pastas de atividade: as 969 gravacoes viravam 56 sequencias, e 42
   delas misturavam as 19 atividades sob o rotulo da primeira linha.

2. Os sensores sao reamostrados numa grade comum, em vez de juntados
   pelo instante exato e filtrados com dropna. Os sensores nao leem no
   mesmo milissegundo: o dropna jogava fora ~98,6% das linhas.

3. Cada janela leva o usuario junto, para separar treino e teste por
   PESSOA. Janelas da mesma gravacao no treino e no teste vazam a
   resposta e inflam a acuracia.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from app.queda import relogio, sinais

PADRAO_WEDA = re.compile(r"(U\d+)_(R\d+)_accel\.csv$")


@dataclass
class Gravacao:
    origem: str  # "weda" ou "apple_watch"
    classe: str  # D01..D11 (atividade) ou F01..F08 (queda)
    usuario: str
    repeticao: str
    caminho: Path

    @property
    def id(self) -> str:
        return f"{self.origem}:{self.classe}/{self.usuario}_{self.repeticao}"

    @property
    def queda(self) -> bool:
        return self.classe.upper().startswith("F")

    @property
    def idoso(self) -> bool:
        # No WEDA, U21 em diante sao os participantes idosos (so fizeram
        # atividades do dia a dia, nenhuma queda). Para as gravacoes do
        # grupo, use usuarios a partir de "I" (ex.: I01) para idosos.
        if self.origem == "weda":
            return int(self.usuario[1:]) >= 21
        return self.usuario.upper().startswith("I")


def listar_weda(pasta: str | Path) -> list[Gravacao]:
    pasta = Path(pasta)
    saida = []
    for pasta_classe in sorted(p for p in pasta.iterdir() if p.is_dir()):
        for arquivo in sorted(pasta_classe.glob("*_accel.csv")):
            achou = PADRAO_WEDA.search(arquivo.name)
            if not achou or "vertical" in arquivo.name:
                continue
            usuario, repeticao = achou.groups()
            saida.append(Gravacao("weda", pasta_classe.name, usuario, repeticao, arquivo))
    return saida


def ler_weda(gravacao: Gravacao) -> np.ndarray:
    base = str(gravacao.caminho)[: -len("_accel.csv")]
    acel = pd.read_csv(gravacao.caminho)
    giro = pd.read_csv(base + "_gyro.csv")
    # WEDA: aceleracao total em m/s2 e giroscopio em rad/s, tempo em s.
    # (Conferido nos dados: em repouso |a| ~ 9,8.)
    return sinais.preparar_gravacao(
        acel.iloc[:, 0].to_numpy(),
        acel.iloc[:, 1:4].to_numpy(),
        giro.iloc[:, 0].to_numpy(),
        giro.iloc[:, 1:4].to_numpy(),
    )


def listar_apple_watch(pasta: str | Path) -> list[Gravacao]:
    """Gravacoes do grupo exportadas do Sensor Logger.

    Estrutura esperada (uma pasta por gravacao, com o WristMotion.csv
    que o app exporta dentro):

        gravacoes_apple_watch/
            F01_U40_R01/WristMotion.csv
            D03_I01_R02/WristMotion.csv
    """
    saida = []
    for arquivo in sorted(Path(pasta).glob("*/WristMotion.csv")):
        nome = arquivo.parent.name
        partes = nome.split("_")
        if len(partes) != 3:
            raise ValueError(f"pasta {nome!r} fora do padrao CLASSE_USUARIO_REPETICAO")
        saida.append(Gravacao("apple_watch", *partes, arquivo))
    return saida


def ler_apple_watch(gravacao: Gravacao) -> np.ndarray:
    tabela = pd.read_csv(gravacao.caminho)
    t, acel, giro = relogio.converter_amostras(tabela.to_dict("records"))
    return sinais.preparar_gravacao(t, acel, t, giro)


def ler(gravacao: Gravacao) -> np.ndarray:
    return ler_weda(gravacao) if gravacao.origem == "weda" else ler_apple_watch(gravacao)


def montar(gravacoes: list[Gravacao]) -> tuple[np.ndarray, np.ndarray, pd.DataFrame]:
    """Devolve (X, y, info). X tem forma (janelas, 125, 4).

    `info` traz, por janela, a gravacao, a classe, o usuario, se e idoso e
    a origem: e com ela que se separa treino e teste por pessoa e se mede
    o alarme falso so nos idosos.
    """
    blocos_x, blocos_y, linhas = [], [], []
    for gravacao in gravacoes:
        s = ler(gravacao)
        jan, inicios = sinais.janelas(s)
        if len(jan) == 0:
            continue
        if gravacao.queda:
            rotulos = sinais.rotular_queda(s, inicios)
        else:
            rotulos = np.zeros(len(inicios), dtype=int)
        manter = rotulos >= 0
        blocos_x.append(jan[manter])
        blocos_y.append(rotulos[manter])
        for _ in range(int(manter.sum())):
            linhas.append(
                {
                    "gravacao": gravacao.id,
                    "origem": gravacao.origem,
                    "classe": gravacao.classe,
                    "usuario": f"{gravacao.origem}:{gravacao.usuario}",
                    "idoso": gravacao.idoso,
                }
            )
    x = np.concatenate(blocos_x) if blocos_x else np.empty((0, sinais.AMOSTRAS_JANELA, 4))
    y = np.concatenate(blocos_y) if blocos_y else np.empty(0, dtype=int)
    return x.astype(np.float32), y, pd.DataFrame(linhas)


# Divisao fixa por pessoa, para o numero do teste ser comparavel entre
# experimentos no MLflow. Mistura adultos (com quedas) e idosos (so
# atividades), para medir recall nos adultos e alarme falso nos idosos.
TESTE_WEDA = ["U03", "U08", "U12", "U22", "U26", "U30"]
VALIDACAO_WEDA = ["U05", "U10", "U24", "U28"]


def separar(info: pd.DataFrame, teste=None, validacao=None) -> pd.Series:
    """'treino' | 'validacao' | 'teste' para cada janela, por usuario."""
    def ids(lista):
        # "U03" vale para o WEDA; gravacoes do grupo vao com a origem:
        # "apple_watch:U41"
        return {u if ":" in u else f"weda:{u}" for u in lista}

    teste = ids(teste or TESTE_WEDA)
    validacao = ids(validacao or VALIDACAO_WEDA)
    return info["usuario"].map(
        lambda u: "teste" if u in teste else "validacao" if u in validacao else "treino"
    )
