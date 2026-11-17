import pandas as pd
import numpy as np
import tensorflow as tf
from tensorflow.keras.preprocessing.sequence import pad_sequences
import joblib

print("Carregando o modelo e artefatos para busca de alerta...")
model = tf.keras.models.load_model('modelo_lstm_weda.keras')
encoder = joblib.load('encoder_classes.pkl')
scaler = joblib.load('scaler_weda.pkl')

df = pd.read_csv('dataset-limpo.csv')

colunas_features = [
    'gyro_x_list', 'gyro_y_list', 'gyro_z_list',
    'accel_x_list', 'accel_y_list', 'accel_z_list',
    'vertical_Accel_x', 'vertical_Accel_y', 'vertical_Accel_z',
    'orientation_s_list', 'orientation_i_list', 'orientation_j_list', 'orientation_k_list'
]

df[colunas_features] = scaler.transform(df[colunas_features])

MAX_LEN = 400
LIMIAR_CONFIANCA = 0.80
encontrou = False

for exemplo_id in df['id_'].unique():
    grupo_exemplo = df[df['id_'] == exemplo_id]
    seq_features = grupo_exemplo[colunas_features].values
    classe_real = grupo_exemplo['classe'].iloc[0]
    
    seq_pad = pad_sequences([seq_features], maxlen=MAX_LEN, padding='post', dtype='float32')
    
    predicoes = model.predict(seq_pad, verbose=0)
    classe_prevista_num = np.argmax(predicoes[0])
    confianca = np.max(predicoes[0])
    classe_prevista_txt = encoder.inverse_transform([classe_prevista_num])[0]
    

    if confianca >= LIMIAR_CONFIANCA and 'F' in classe_prevista_txt:
        print(f"\n--- Amostra Encontrada! ---")
        print(f"ID Testado: {exemplo_id}")
        print(f"Classe Real: {classe_real} | Prevista: {classe_prevista_txt}")
        print(f"Nível de Confiança: {confianca * 100:.2f}%")
        print(f"\n ALERTA CRÍTICO! Queda detectada com alta certeza ({confianca * 100:.2f}%). [Mensagem enviada para o WhatsApp da família]")
        encontrou = True
        break

if not encontrou:
    print("\n Nenhuma amostra atingiu o limiar de 80% de confiança para quedas nesta busca.")