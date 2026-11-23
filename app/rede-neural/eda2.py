import pandas as pd
import numpy as np

df = pd.read_csv('dataset.csv')

colunas_principais = [
    'gyro_x_list', 'gyro_y_list', 'gyro_z_list',
    'accel_x_list', 'accel_y_list', 'accel_z_list',
    'orientation_s_list', 'orientation_i_list', 'orientation_j_list', 'orientation_k_list'
]
colunas_vertical = ['vertical_Accel_x', 'vertical_Accel_y', 'vertical_Accel_z']
todas_features = colunas_principais + colunas_vertical

df['time_td'] = pd.to_timedelta(df['time'], unit='s')

# 01: reamostragem temporal 
def processar_evento(grupo):
    
    if grupo['accel_x_list'].isnull().all() or grupo['gyro_x_list'].isnull().all():
        return pd.DataFrame()
    
    classe = grupo['classe'].iloc[0]
    id_val = grupo.name
    
    
    res = grupo.set_index('time_td')[todas_features].resample('20ms').mean()
    
    
    res[todas_features] = res[todas_features].interpolate(method='linear', limit_direction='both')
    res[todas_features] = res[todas_features].ffill().bfill()
    
    
    res[colunas_vertical] = res[colunas_vertical].fillna(0.0)
    
    res['id_'] = id_val
    res['classe'] = classe
    
    
    res = res.reset_index()
    res['time'] = res['time_td'].dt.total_seconds()
    res = res.drop(columns=['time_td'])
    
    return res

print("2. Aplicando reamostragem (50Hz) e imputação temporal isolada por id_...")
df_limpo = df.groupby('id_', group_keys=False).apply(processar_evento, include_groups=False)

# 02: calculo erro estatístico da imputação
np.random.seed(42)
print("\nERRO ESTATÍSTICO DA IMPUTAÇÃO (SIMULAÇÃO DE 10% DE FALHAS)")
for col in ['accel_x_list', 'gyro_x_list', 'orientation_s_list']:
    serie_base = df_limpo[col].iloc[:5000].copy()
    mascara = np.random.rand(len(serie_base)) < 0.10
    
    serie_falha = serie_base.copy()
    serie_falha[mascara] = np.nan
    serie_rec = serie_falha.interpolate(method='linear').ffill().bfill()
    
    diff = serie_base[mascara] - serie_rec[mascara]
    mae = np.mean(np.abs(diff))
    rmse = np.sqrt(np.mean(diff**2))
    print(f"{col}: MAE = {mae:.5f} | RMSE = {rmse:.5f}")

# 03: resumo e exportação
print(f"\nRESUMO DO DATASET TRATADO")
print(f"Eventos (id_) preservados: {df_limpo['id_'].nunique()} de {df['id_'].nunique()}")
print(f"Total de linhas (janelas de 20ms): {len(df_limpo)}")
print(f"Distribuicao de classes (por evento):")
print(df_limpo.groupby('id_')['classe'].first().value_counts())
print(f"Nulos restantes: {df_limpo[todas_features].isnull().sum().sum()}")


colunas_finais = ['id_', 'time'] + todas_features + ['classe']
df_limpo = df_limpo[colunas_finais]

df_limpo.to_csv('dataset-limpo-v2.csv', index=False)
print("\nArquivo 'dataset-limpo-v2.csv' salvo com sucesso!")