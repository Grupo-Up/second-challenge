import pandas as pd
import matplotlib.pyplot as plt
from sklearn.model_selection import train_test_split
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple, Union

FATOR_TUKEY = 1.5
LIMITE_VIF_MODERADO = 5
LIMITE_VIF_ALTO = 10
NOMES_CLASSES = {"F01":"Fall forward while walking caused by a slip", 
                "F02":"Lateral fall while walking caused by a slip",
                "F03":"Fall backward while walking caused by a slip",
                "F04":"Fall forward while walking caused by a trip",
                "F05":"Fall backward when trying to sit down",
                "F06":"Fall forward while sitting, caused by fainting or falling asleep",
                "F07":"Fall backward while sitting, caused by fainting or falling asleep",
                "F08":"Lateral fall while sitting, caused by fainting or falling asleep}",
                "D01":"Walking",
                "D02":"Jogging",
                "D03":"Walking up and downstairs",
                "D04":"Sitting on a chair, wait a moment, and get up",
                "D05":"Sitting a moment, attempt to get up and collapse into a chair",
                "D06":"Crouching (bending at the knees), tie shoes, and get up",
                "D07":"Stumble while walking",
                "D08":"Gently jump without falling (trying to reach high object)",
                "D09":"Hit table with hand",
                "D10":"Clapping Hands",
                "D11":"Opening and closing door"}

# Carregando o dataset
path = Path("./app/rede neural/dataset")

lista_dfs = []

for pasta_classe in path.iterdir():
    if pasta_classe.is_dir():
        nome_classe = pasta_classe.name
        for arquivo_csv in pasta_classe.rglob("*.csv"):
            df_temp = pd.read_csv(arquivo_csv)
            df_temp["classe"] = nome_classe
            df_temp["arquivo_id"] = arquivo_csv.stem
            
            lista_dfs.append(df_temp)

# 4. Junta tudo em um único DataFrame
dataset_completo = pd.concat(lista_dfs, ignore_index=True)

print(dataset_completo.head())
print(dataset_completo["classe"].value_counts())

#df = pd.read_csv('dataset.csv')
#df_test, df_train = df[df['split'] == 'test'], df[df['split'] == 'train']

#no_fall-train = df_train[df_train['Decision'] == 0]
#uncertain-train = df_train[df_train['Decision'] == 1]
#fall-train = df_train[df_train['Decision'] == 2]

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


