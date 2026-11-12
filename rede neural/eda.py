import pandas as pd
import matplotlib.pyplot as plt
from sklearn.model_selection import train_test_split

FATOR_TUKEY = 1.5
LIMITE_VIF_MODERADO = 5
LIMITE_VIF_ALTO = 10
NOMES_CLASSES = {0: "no fall", 1: "uncertain", 2: "fall"}

# Carregando o dataset
df = pd.read_csv('dataset.csv')
df_test, df_train = df[df['split'] == 'test'], df[df['split'] == 'train']

no_fall-train = df_train[df_train['Decision'] == 0]
uncertain-train = df_train[df_train['Decision'] == 1]
fall-train = df_train[df_train['Decision'] == 2]

#Funções de análise exploratória de dados (EDA)
def resumo_descritivo(features: pd.DataFrame, casas_moda: int = 3) -> pd.DataFrame:
    """Estatísticas descritivas vetorizadas, uma linha por feature."""
    quartis = features.quantile([0.25, 0.5, 0.75])
    q1, mediana, q3 = quartis.loc[0.25], quartis.loc[0.5], quartis.loc[0.75]
    iqr = q3 - q1
    n_outliers = ((features < q1 - FATOR_TUKEY * iqr) | (features > q3 + FATOR_TUKEY * iqr)).sum()

    modas = features.round(casas_moda).mode()
    media = features.mean()
    desvio_padrao = features.std(ddof=1)

    return pd.DataFrame(
        {
            "media": media,
            "mediana": mediana,
            "moda": modas.iloc[0],
            "n_modas": modas.notna().sum(),
            "desvio_padrao": desvio_padrao,
            "coef_variacao": desvio_padrao / media.replace(0, pd.NA),
            "min": features.min(),
            "q1": q1,
            "q3": q3,
            "max": features.max(),
            "iqr": iqr,
            "assimetria": features.skew(),
            "curtose_excesso": features.kurt(),
            "n_outliers_tukey": n_outliers,
            "pct_zeros": (features == 0).mean() * 100,
        }
    )

def resumo_por_classe(features: pd.DataFrame, label: pd.Series) -> pd.DataFrame:
    """`resumo_descritivo` separado por classe."""
    resumos = {
        NOMES_CLASSES[valor]: resumo_descritivo(features[label == valor])
        for valor in sorted(label.unique())
    }
    return pd.concat(resumos, names=["classe", "feature"])


