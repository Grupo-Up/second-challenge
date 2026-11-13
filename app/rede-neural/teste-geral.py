import pandas as pd
import numpy as np
import tensorflow as tf
from tensorflow.keras.preprocessing.sequence import pad_sequences
from sklearn.metrics import accuracy_score, classification_report
import joblib

print("Carregando o modelo e os artefatos para avaliação geral...")
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


X_sequences = []
y_reais = []

for id_val, grupo in df.groupby('id_'):
    seq_features = grupo[colunas_features].values
    rotulo = grupo['classe'].iloc[0]
    X_sequences.append(seq_features)
    y_reais.append(rotulo)

MAX_LEN = 400
X_pad = pad_sequences(X_sequences, maxlen=MAX_LEN, padding='post', dtype='float32')

print(f"\nAvaliando {len(X_pad)} sequências completas do dataset...")


predicoes = model.predict(X_pad, verbose=0)
y_pred_nums = np.argmax(predicoes, axis=1)
y_pred_txts = encoder.inverse_transform(y_pred_nums)

y_reais_arr = np.array(y_reais)

acuracia = accuracy_score(y_reais_arr, y_pred_txts)
print(f"\n Acurácia Geral no Dataset Completo: {acuracia * 100:.2f}%")

print("\nRelatório de Classificação Detalhado:")
print(classification_report(y_reais_arr, y_pred_txts, zero_division=0))