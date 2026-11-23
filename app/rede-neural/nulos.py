'''import pandas as pd

df = pd.read_csv('dataset.csv')

colunas_sensores = [
    'gyro_x_list', 'gyro_y_list', 'gyro_z_list',
    'accel_x_list', 'accel_y_list', 'accel_z_list',
    'vertical_Accel_x', 'vertical_Accel_y', 'vertical_Accel_z',
    'orientation_s_list', 'orientation_i_list', 'orientation_j_list', 'orientation_k_list'
]

nulos_qtd = df[colunas_sensores].isnull().sum()
nulos_pct = (nulos_qtd / len(df)) * 100

diagnostico = pd.DataFrame({
    'Faltantes (Qtd)': nulos_qtd,
    'Faltantes (%)': nulos_pct.round(2)
}).sort_values(by='Faltantes (%)', ascending=False)

print("DIAGNÓSTICO POR SENSOR")
print(diagnostico)

def max_gap(serie):
    is_na = serie.isnull()
    return is_na.groupby((~is_na).cumsum()).sum().max()

gaps = df.groupby('id_')[colunas_sensores].apply(lambda g: g.apply(max_gap)).max()
print("\nMAIOR SEQUÊNCIA CONTÍNUA DE NULOS (EM LINHAS)")
print(gaps)'''


'''import pandas as pd
import numpy as np

df = pd.read_csv('dataset.csv')

print("Colunas disponíveis:", list(df.columns))

primeiro_id = df['id_'].iloc[0]
amostra = df[df['id_'] == primeiro_id].head(20)
print(f"\n=== PADRÃO MILISSEGUNDO A MILISSEGUNDO (id_: {primeiro_id}) ===")
print(amostra[['accel_x_list', 'gyro_x_list', 'vertical_Accel_x', 'orientation_s_list']])

cols_tempo = [c for c in df.columns if 'time' in c.lower() or 'stamp' in c.lower() or 'ms' in c.lower()]
if cols_tempo:
    col_t = cols_tempo[0]
    deltas = df.groupby('id_')[col_t].diff().dropna()
    print(f"\n=== INTERVALO ENTRE LEITURAS ({col_t}) ===")
    print(f"Mediana do intervalo: {deltas.median()} | Máximo intervalo (maior travamento): {deltas.max()}")'''



import pandas as pd

df = pd.read_csv('dataset.csv')

colunas_sensores = [
    'gyro_x_list', 'gyro_y_list', 'gyro_z_list',
    'accel_x_list', 'accel_y_list', 'accel_z_list',
    'vertical_Accel_x', 'vertical_Accel_y', 'vertical_Accel_z',
    'orientation_s_list', 'orientation_i_list', 'orientation_j_list', 'orientation_k_list'
]

df['time_td'] = pd.to_timedelta(df['time'], unit='s')

def reamostrar_grupo(grupo):
    classe = grupo['classe'].iloc[0]
    id_val = grupo.name  
    
    
    res = grupo.set_index('time_td')[colunas_sensores].resample('20ms').mean()
    res['id_'] = id_val
    res['classe'] = classe
    return res.reset_index()

df_50hz = df.groupby('id_', group_keys=False).apply(reamostrar_grupo, include_groups=False)

print(" APÓS ALINHAR O RELÓGIO PARA 20ms (50Hz)")
print("Porcentagem de nulos ANTES mesmo de interpolar:")
print((df_50hz[colunas_sensores].isnull().mean() * 100).round(2))