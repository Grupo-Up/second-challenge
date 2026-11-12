import pandas as pd
import matplotlib.pyplot as plt
from sklearn.model_selection import train_test_split

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

df = pd.read_csv('./app/rede-neural/dataset-limpo.csv')

#Funções de análise exploratória de dados (EDA)
def resumo_descritivo(features: pd.DataFrame, casas_moda: int = 3) -> pd.DataFrame:
    """Estatísticas descritivas vetorizadas, uma linha por feature."""
    # 1. Mantém apenas colunas numéricas (ignora textos e datas)
    features_numericas = features.select_dtypes(include="number")

    # 2. Remove a coluna "id_" ou qualquer coluna que comece com "id_"
    colunas_validas = [col for col in features_numericas.columns if not col.startswith("id_")]
    features_validas = features_numericas[colunas_validas]

    # 3. Verifica se sobrou alguma coluna numérica antes de calcular
    if not features_validas.empty:
        quartis = features_validas.quantile([0.25, 0.5, 0.75])
        q1, mediana, q3 = quartis.loc[0.25], quartis.loc[0.5], quartis.loc[0.75]
        iqr = q3 - q1
        n_outliers = ((features_validas < q1 - FATOR_TUKEY * iqr) | (features_validas > q3 + FATOR_TUKEY * iqr)).sum()

        modas = features_validas.round(casas_moda).mode()
        media = features_validas.mean()
        desvio_padrao = features_validas.std(ddof=1)

        return pd.DataFrame(
            {
                "media": media,
                "mediana": mediana,
                "moda": modas.iloc[0],
                "n_modas": modas.notna().sum(),
                "desvio_padrao": desvio_padrao,
                "coef_variacao": desvio_padrao / media.replace(0, pd.NA),
                "min": features_validas.min(),
                "q1": q1,
                "q3": q3,
                "max": features_validas.max(),
                "iqr": iqr,
                "assimetria": features_validas.skew(),
                "curtose_excesso": features_validas.kurt(),
                "n_outliers_tukey": n_outliers,
                "pct_zeros": (features_validas == 0).mean() * 100,
            }
        )



def resumo_por_classe(features: pd.DataFrame, label: pd.Series) -> pd.DataFrame:
    """`resumo_descritivo` separado por classe."""
    resumos = {
        NOMES_CLASSES[valor]: resumo_descritivo(features[label == valor])
        for valor in sorted(label.unique())
    }
    return pd.concat(resumos, names=["classe", "feature"])

print(resumo_descritivo(df).head())