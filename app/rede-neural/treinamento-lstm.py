import pandas as pd
import numpy as np
import tensorflow as tf
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import LSTM, Dense, Dropout, Input
from tensorflow.keras.preprocessing.sequence import pad_sequences
from sklearn.preprocessing import StandardScaler, LabelEncoder
from sklearn.model_selection import train_test_split
import joblib

df = pd.read_csv('dataset-limpo.csv')

colunas_features = [
    'gyro_x_list', 'gyro_y_list', 'gyro_z_list',
    'accel_x_list', 'accel_y_list', 'accel_z_list',
    'vertical_Accel_x', 'vertical_Accel_y', 'vertical_Accel_z',
    'orientation_s_list', 'orientation_i_list', 'orientation_j_list', 'orientation_k_list'
]

encoder = LabelEncoder()
df['classe_num'] = encoder.fit_transform(df['classe'])
joblib.dump(encoder, 'encoder_classes.pkl')

# Padroniza as features dos sensore
scaler = StandardScaler()
df[colunas_features] = scaler.fit_transform(df[colunas_features])
joblib.dump(scaler, 'scaler_weda.pkl')

X_sequences = []
y_labels = []

for id_val, grupo in df.groupby('id_'):
    seq_features = grupo[colunas_features].values
    rotulo = grupo['classe_num'].iloc[0]
    X_sequences.append(seq_features)
    y_labels.append(rotulo)

MAX_LEN = 400
X_pad = pad_sequences(X_sequences, maxlen=MAX_LEN, padding='post', dtype='float32')
y_arr = np.array(y_labels)

print(f"Formato das sequências preparadas para a LSTM: {X_pad.shape}")

X_train, X_test, y_train, y_test = train_test_split(X_pad, y_arr, test_size=0.2, random_state=42, stratify=y_arr)


num_classes = len(encoder.classes_)
print(f"Total de classes cadastradas no modelo: {num_classes}")

# --- 4. CONSTRUÇÃO DA REDE LSTM ---
model = Sequential([
    Input(shape=(MAX_LEN, len(colunas_features))),
    LSTM(64, return_sequences=False),
    Dropout(0.3),
    Dense(32, activation='relu'),
    Dropout(0.2),
    Dense(num_classes, activation='softmax')
])

model.compile(
    optimizer='adam',
    loss='sparse_categorical_crossentropy',
    metrics=['accuracy']
)

print("\nIniciando o treinamento da LSTM...")
history = model.fit(
    X_train, y_train,
    epochs=25,
    batch_size=8,
    validation_split=0.1,
    verbose=1
)

model.save('modelo_lstm_weda.keras')
print("\n Modelo LSTM treinado e salvo com sucesso!")
