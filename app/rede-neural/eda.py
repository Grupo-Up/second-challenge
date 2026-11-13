import pandas as pd
import matplotlib.pyplot as plt
from sklearn.model_selection import train_test_split
from pathlib import Path

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

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "plots"

df = pd.read_csv('./app/rede-neural/dataset-limpo.csv')
df_train, df_test = train_test_split(df, test_size=0.2, random_state=42)
features_validas = df_train.select_dtypes(include="number")
features_validas = features_validas.drop(columns=["time"])
#Funções de análise exploratória de dados (EDA)
def resumo_descritivo(features: pd.DataFrame, casas_moda: int = 3) -> pd.DataFrame:
    """Estatísticas descritivas vetorizadas, uma linha por feature."""
    features_numericas = features.select_dtypes(include="number").drop(
        columns=["time"], errors="ignore"
    )
    if not features_numericas.empty:
        quartis = features_numericas.quantile([0.25, 0.5, 0.75])
        q1, mediana, q3 = quartis.loc[0.25], quartis.loc[0.5], quartis.loc[0.75]
        iqr = q3 - q1
        n_outliers = (
            (features_numericas < (q1 - FATOR_TUKEY * iqr))
            | (features_numericas > (q3 + FATOR_TUKEY * iqr))
        ).sum()

        modas = features_numericas.round(casas_moda).mode()
        media = features_numericas.mean()
        desvio_padrao = features_numericas.std(ddof=1)

        resumo = pd.DataFrame(
            {
                "media": media,
                "mediana": mediana,
                "moda": modas.iloc[0],
                "n_modas": modas.notna().sum(),
                "desvio_padrao": desvio_padrao,
                "coef_variacao": desvio_padrao / media.replace(0, pd.NA),
                "min": features_numericas.min(),
                "q1": q1,
                "q3": q3,
                "max": features_numericas.max(),
                "iqr": iqr,
                "assimetria": features_numericas.skew(),
                "curtose_excesso": features_numericas.kurt(),
                "n_outliers_tukey": n_outliers,
                "pct_zeros": (features_numericas == 0).mean() * 100,
            }
        )
        return resumo.rename_axis("coluna").reset_index()
    return pd.DataFrame(columns=["coluna"])

def resumo_por_classe(features: pd.DataFrame, label: pd.Series) -> pd.DataFrame:
    """Calcula o resumo descritivo separadamente para cada classe."""
    resumos = []
    for valor in sorted(label.dropna().unique()):
        resumo = resumo_descritivo(features.loc[label == valor])
        resumo.insert(0, "classe", NOMES_CLASSES.get(valor, str(valor)))
        resumos.append(resumo)

    if not resumos:
        return pd.DataFrame(columns=["classe", "coluna"])
    return pd.concat(resumos, ignore_index=True)

def create_histograms():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for coluna in list(features_validas.columns):
        coluna_dir = OUTPUT_DIR / str(coluna)
        coluna_dir.mkdir(parents=True, exist_ok=True)
        for classe in NOMES_CLASSES.keys():
            df_col = df_train[df_train["classe"] == classe]
            fig, ax = plt.subplots()
            ax.hist(df_col[coluna].dropna(), bins=30, color="steelblue", edgecolor="black")
            ax.set_title(f'Distribuição de {coluna} (Classe: {classe})')
            ax.set_xlabel(coluna)
            ax.set_ylabel('Frequência')
            ax.grid(axis='y', linestyle='--', alpha=0.7)
            fig.tight_layout()
            fig.savefig(coluna_dir / f'histograma_{classe}.png', dpi=300, bbox_inches='tight')
            plt.close(fig)
    return

df_analysis = resumo_por_classe(df_train, df_train["classe"])
df_analysis.to_csv('./app/rede-neural/analysis.csv', index=False, encoding='utf-8')

#fazer correlacao com classes e vif!!! 