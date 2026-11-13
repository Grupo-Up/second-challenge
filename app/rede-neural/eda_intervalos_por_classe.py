from pathlib import Path
import re

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split


BASE_DIR = Path(__file__).resolve().parent
DATASET_PATH = BASE_DIR / "dataset-limpo.csv"
OUTPUT_DIR = BASE_DIR / "plots_intervalos_2_5s"
INTERVALO_SEGUNDOS = 2.5
TEST_SIZE = 0.2
RANDOM_STATE = 42


def preparar_dados_treino(dados: pd.DataFrame) -> tuple[pd.DataFrame, list[str], list[str]]:
    """Separa treino e cria intervalos sem descartar linhas do conjunto de treino."""
    colunas_obrigatorias = {"time", "classe"}
    ausentes = colunas_obrigatorias.difference(dados.columns)
    if ausentes:
        raise ValueError(f"Colunas obrigatorias ausentes: {sorted(ausentes)}")

    dados_treino, _ = train_test_split(
        dados, test_size=TEST_SIZE, random_state=RANDOM_STATE
    )
    dados_treino = dados_treino.copy()
    dados_treino["time"] = pd.to_numeric(dados_treino["time"], errors="raise")
    if dados_treino[["time", "classe"]].isna().any().any():
        raise ValueError("O conjunto de treino contem 'time' ou 'classe' nulo.")
    if not np.isfinite(dados_treino["time"].to_numpy(dtype=float)).all():
        raise ValueError("A coluna 'time' contem valores nao finitos no treino.")

    features = dados_treino.select_dtypes(include="number").columns.drop("time")
    if len(features) == 0:
        raise ValueError("Nenhuma coluna numerica de feature foi encontrada.")
    valores_features = dados_treino[features].to_numpy(dtype=float)
    if not np.isfinite(valores_features).all():
        raise ValueError("Ha valores ausentes ou nao finitos nas features do treino.")

    dados_treino["time_inicio"] = (
        np.floor(dados_treino["time"] / INTERVALO_SEGUNDOS)
        * INTERVALO_SEGUNDOS
    ).round(10)
    classes = sorted(dados_treino["classe"].unique())
    return dados_treino, list(features), classes


def resumir_intervalos(
    dados: pd.DataFrame, features: list[str], classes: list[str]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Cria estatisticas descritivas e contagens para cada janela e classe."""
    resumo_linhas = []
    contagem_linhas = []

    for inicio, dados_intervalo in dados.groupby("time_inicio", sort=True):
        fim = inicio + INTERVALO_SEGUNDOS
        por_classe = {
            classe: grupo
            for classe, grupo in dados_intervalo.groupby("classe", sort=False)
        }
        for classe in classes:
            grupo = por_classe.get(classe)
            n_amostras = 0 if grupo is None else len(grupo)
            contagem_linhas.append(
                {
                    "time_inicio": inicio,
                    "time_fim": fim,
                    "classe": classe,
                    "n_amostras": n_amostras,
                }
            )
            for feature in features:
                valores = pd.Series(dtype=float) if grupo is None else grupo[feature]
                resumo_linhas.append(
                    {
                        "time_inicio": inicio,
                        "time_fim": fim,
                        "classe": classe,
                        "feature": feature,
                        "n_amostras": n_amostras,
                        "media": valores.mean(),
                        "mediana": valores.median(),
                        "desvio_padrao": valores.std(),
                        "min": valores.min(),
                        "q1": valores.quantile(0.25),
                        "q3": valores.quantile(0.75),
                        "max": valores.max(),
                    }
                )

    return pd.DataFrame(resumo_linhas), pd.DataFrame(contagem_linhas)


def nome_arquivo_feature(feature: str, inicio: float) -> str:
    """Gera um nome de arquivo que inclui feature e limites do intervalo."""
    feature_segura = re.sub(r"[^A-Za-z0-9_-]+", "_", feature).strip("_")
    inicio_ms = round(inicio * 1000)
    fim_ms = round((inicio + INTERVALO_SEGUNDOS) * 1000)
    return f"{feature_segura}_time_{inicio_ms:07d}_{fim_ms:07d}.png"


def plotar_histogramas_por_intervalo(
    dados: pd.DataFrame,
    features: list[str],
    classes: list[str],
    pasta_saida: Path,
) -> None:
    """Salva um subplot de histograma por classe, feature e intervalo."""
    pasta_saida.mkdir(parents=True, exist_ok=True)
    paleta = plt.get_cmap("tab20")
    n_colunas = min(4, len(classes))
    n_linhas = int(np.ceil(len(classes) / n_colunas))

    for inicio, grupo_intervalo in dados.groupby("time_inicio", sort=True):
        fim = inicio + INTERVALO_SEGUNDOS
        for feature in features:
            valores_todos = grupo_intervalo[feature].to_numpy(dtype=float)
            bins = np.histogram_bin_edges(valores_todos, bins=30)
            fig, eixos = plt.subplots(
                n_linhas,
                n_colunas,
                figsize=(4.5 * n_colunas, 3.2 * n_linhas),
                sharex=True,
                squeeze=False,
            )
            for indice, classe in enumerate(classes):
                linha, coluna_eixo = divmod(indice, n_colunas)
                ax = eixos[linha, coluna_eixo]
                valores = grupo_intervalo.loc[
                    grupo_intervalo["classe"] == classe, feature
                ].to_numpy(dtype=float)
                if valores.size:
                    ax.hist(
                        valores,
                        bins=bins,
                        color=paleta(indice % 20),
                        edgecolor="black",
                    )
                else:
                    ax.text(
                        0.5,
                        0.5,
                        "Sem amostras neste intervalo",
                        ha="center",
                        va="center",
                        transform=ax.transAxes,
                    )
                ax.set_title(f"{classe} (n={len(valores)})")
                ax.set_xlabel(feature)
                ax.set_ylabel("Frequencia")
                ax.grid(axis="y", linestyle="--", alpha=0.5)

            for indice in range(len(classes), n_linhas * n_colunas):
                linha, coluna_eixo = divmod(indice, n_colunas)
                eixos[linha, coluna_eixo].set_visible(False)

            fig.suptitle(
                f"Distribuicao de {feature} por classe | time [{inicio:g}, {fim:g})"
            )
            fig.tight_layout()
            fig.savefig(pasta_saida / nome_arquivo_feature(feature, inicio), dpi=150)
            plt.close(fig)


def plotar_boxplots_por_intervalo(
    dados: pd.DataFrame,
    features: list[str],
    classes: list[str],
    pasta_saida: Path,
) -> None:
    """Salva um subplot de boxplot por classe, feature e intervalo."""
    pasta_saida.mkdir(parents=True, exist_ok=True)
    n_colunas = min(4, len(classes))
    n_linhas = int(np.ceil(len(classes) / n_colunas))

    for inicio, grupo_intervalo in dados.groupby("time_inicio", sort=True):
        fim = inicio + INTERVALO_SEGUNDOS
        for feature in features:
            fig, eixos = plt.subplots(
                n_linhas,
                n_colunas,
                figsize=(4.5 * n_colunas, 3.2 * n_linhas),
                sharey=True,
                squeeze=False,
            )
            for indice, classe in enumerate(classes):
                linha, coluna_eixo = divmod(indice, n_colunas)
                ax = eixos[linha, coluna_eixo]
                valores = grupo_intervalo.loc[
                    grupo_intervalo["classe"] == classe, feature
                ].to_numpy(dtype=float)
                if valores.size:
                    ax.boxplot(valores, showfliers=False)
                    ax.set_xticks([])
                else:
                    ax.text(
                        0.5,
                        0.5,
                        "Sem amostras neste intervalo",
                        ha="center",
                        va="center",
                        transform=ax.transAxes,
                    )
                ax.set_title(f"{classe} (n={len(valores)})")
                ax.set_ylabel(feature)
                ax.grid(axis="y", linestyle="--", alpha=0.5)

            for indice in range(len(classes), n_linhas * n_colunas):
                linha, coluna_eixo = divmod(indice, n_colunas)
                eixos[linha, coluna_eixo].set_visible(False)

            fig.suptitle(f"Boxplot de {feature} por classe | time [{inicio:g}, {fim:g})")
            fig.tight_layout()
            fig.savefig(pasta_saida / nome_arquivo_feature(feature, inicio), dpi=150)
            plt.close(fig)


def plotar_series_temporais_por_intervalo(
    dados: pd.DataFrame,
    features: list[str],
    classes: list[str],
    pasta_saida: Path,
) -> None:
    """Salva um subplot de serie temporal por classe, feature e intervalo."""
    pasta_saida.mkdir(parents=True, exist_ok=True)
    paleta = plt.get_cmap("tab20")
    n_colunas = min(4, len(classes))
    n_linhas = int(np.ceil(len(classes) / n_colunas))

    for inicio, grupo_intervalo in dados.groupby("time_inicio", sort=True):
        fim = inicio + INTERVALO_SEGUNDOS
        for feature in features:
            fig, eixos = plt.subplots(
                n_linhas,
                n_colunas,
                figsize=(4.5 * n_colunas, 3.2 * n_linhas),
                sharex=True,
                sharey=True,
                squeeze=False,
            )
            for indice, classe in enumerate(classes):
                linha, coluna_eixo = divmod(indice, n_colunas)
                ax = eixos[linha, coluna_eixo]
                classe_dados = grupo_intervalo.loc[
                    grupo_intervalo["classe"] == classe
                ]
                if classe_dados.empty:
                    ax.text(
                        0.5,
                        0.5,
                        "Sem amostras neste intervalo",
                        ha="center",
                        va="center",
                        transform=ax.transAxes,
                    )
                else:
                    ax.scatter(
                        classe_dados["time"],
                        classe_dados[feature],
                        s=14,
                        alpha=0.65,
                        color=paleta(indice % 20),
                    )
                ax.set_title(f"{classe} (n={len(classe_dados)})")
                ax.set_xlim(inicio, fim)
                ax.set_xlabel("Time (s)")
                ax.set_ylabel(feature)
                ax.grid(axis="both", linestyle="--", alpha=0.5)

            for indice in range(len(classes), n_linhas * n_colunas):
                linha, coluna_eixo = divmod(indice, n_colunas)
                eixos[linha, coluna_eixo].set_visible(False)

            fig.suptitle(f"{feature} por classe | time [{inicio:g}, {fim:g})")
            fig.tight_layout()
            fig.savefig(pasta_saida / nome_arquivo_feature(feature, inicio), dpi=150)
            plt.close(fig)


def main() -> None:
    dados = pd.read_csv(DATASET_PATH)
    dados_treino, features, classes = preparar_dados_treino(dados)
    pasta_estatisticas = OUTPUT_DIR / "estatisticas"
    pasta_estatisticas.mkdir(parents=True, exist_ok=True)

    resumo, contagens = resumir_intervalos(dados_treino, features, classes)
    resumo.to_csv(
        pasta_estatisticas / "resumo_por_intervalo_e_classe.csv",
        index=False,
        encoding="utf-8",
    )
    contagens.to_csv(
        pasta_estatisticas / "contagem_por_intervalo_e_classe.csv",
        index=False,
        encoding="utf-8",
    )

    plotar_histogramas_por_intervalo(
        dados_treino, features, classes, OUTPUT_DIR / "histogramas"
    )
    plotar_boxplots_por_intervalo(
        dados_treino, features, classes, OUTPUT_DIR / "boxplots"
    )
    plotar_series_temporais_por_intervalo(
        dados_treino, features, classes, OUTPUT_DIR / "series_temporais"
    )


if __name__ == "__main__":
    main()
