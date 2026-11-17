import pandas as pd
import matplotlib.pyplot as plt
from sklearn.model_selection import train_test_split
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple, Union
from functools import reduce

path = Path("./app/rede-neural/dataset")
lista_classes = []

for pasta_classe in path.iterdir():
    if pasta_classe.is_dir():
        nome_classe = pasta_classe.name
        arquivos_por_id = {}
        
        for arquivo_csv in pasta_classe.rglob("*.csv"):
            df_temp = pd.read_csv(arquivo_csv)
            
            mapa_colunas = {col: "time" for col in df_temp.columns if "time" in col.lower()}
            df_temp = df_temp.rename(columns=mapa_colunas)
            
            partes = arquivo_csv.name.split('_')
            id_atual = f"{partes[0]}_{partes[1]}"
            df_temp["id_"] = id_atual
            
            arquivos_por_id.setdefault(id_atual, []).append(df_temp)
            
        dfs_da_classe = []
        for id_atual, lista_sensores in arquivos_por_id.items():
            df_id = reduce(
                lambda left, right: pd.merge(left, right, on=["id_", "time"], how="outer"), 
                lista_sensores
            )
            dfs_da_classe.append(df_id)
            
        if dfs_da_classe:
            dataset_aux = pd.concat(dfs_da_classe, ignore_index=True)
            dataset_aux["classe"] = nome_classe
            lista_classes.append(dataset_aux)

# 5. Consolida todas as classes no dataset final
dataset_completo = pd.concat(lista_classes, ignore_index=True)
colunas = ['id_'] + [col for col in dataset_completo.columns if col != 'id_']
dataset_completo = dataset_completo[colunas]
dataset_limpo = dataset_completo.dropna()

print(dataset_completo.head())
print(dataset_completo["classe"].value_counts())
dataset_completo.to_csv('./app/rede-neural/dataset.csv', index=False, encoding='utf-8')
dataset_limpo.to_csv('./app/rede-neural/dataset-limpo.csv', index=False, encoding='utf-8')