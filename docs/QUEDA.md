# Detector de quedas com Apple Watch

A rede neural do projeto. O Apple Watch da pessoa idosa mede o movimento do pulso, uma LSTM decide se aquilo foi uma queda e, se foi, o grupo da família recebe um alerta no WhatsApp com a orientação do Guia do Cuidador. A família responde se foi queda ou alarme falso, e essa resposta volta para a avaliação do modelo.

```text
Apple Watch ──► iPhone (Sensor Logger) ──HTTP──► POST /sensor/sensorlogger
                                                   │  buffer de 2,5 s por relógio
                                                   ▼
                                               LSTM (app/queda/detector.py)
                                                   │  probabilidade ≥ limiar?
                                                   ▼
                                               tabela alertas_queda (pendente)
                                                   │  o bot busca a cada 5 s
                                                   ▼
                         grupo do WhatsApp: alerta + orientação do Guia (!duvida)
                                                   │
                         "!queda ok" / "!queda falso" ──► status do alerta (MLOps)
```

Não precisa de Mac nem de Xcode: o Sensor Logger (gratuito na App Store) faz o papel do app do relógio.

---

## 1. O que mudou em relação à rede antiga

A LSTM em `app/rede-neural/` tinha problemas no preparo dos dados que tornavam o resultado inválido. A pasta antiga continua lá, como histórico; o código novo está em `app/queda/`.

| Problema | Efeito | Correção |
| --- | --- | --- |
| `id_ = "U01_R01"` se repete nas 19 pastas de atividade | 969 gravações viravam 56 sequências; 42 misturavam as 19 atividades sob o rótulo da primeira linha | identificador = classe + usuário + repetição |
| sensores juntados pelo instante exato + `dropna` | ~98,6% das linhas descartadas | reamostragem numa grade comum de 50 Hz |
| quedas gravadas a ~40 Hz, atividades a ~50 Hz | a rede podia aprender a frequência de gravação em vez da queda | tudo reamostrado para 50 Hz |
| scaler ajustado antes de separar treino e teste | vazamento de informação do teste | média e desvio só do treino |
| divisão aleatória | janelas da mesma pessoa no treino e no teste | divisão **por pessoa** |
| teste no dataset inteiro | o número publicado media o treino | teste só com pessoas que a rede nunca viu |
| 19 classes de saída | o alerta só precisa de "queda ou não" | saída binária |
| eixos x, y, z do relógio do WEDA | não correspondem aos do Apple Watch | 4 sinais que não dependem do aparelho nem do pulso |

Os 4 sinais (em `app/queda/sinais.py`): módulo da aceleração, módulo da velocidade angular, aceleração na direção da gravidade e aceleração no plano horizontal. Há um teste automático que gira o relógio e confere que os sinais não mudam.

## 2. Arquivos

| Arquivo | O que faz |
| --- | --- |
| `app/queda/sinais.py` | Pré-processamento. **O mesmo no treino e na API** — se divergir, o teste deixa de valer. |
| `app/queda/relogio.py` | Lê o Wrist Motion do Sensor Logger (g ou m/s², detectado sozinho) e converte para SI. |
| `app/queda/dados.py` | Monta o dataset (WEDA + gravações do grupo) e separa treino/validação/teste por pessoa. |
| `app/queda/avaliacao.py` | Métricas: recall de quedas, alarmes falsos por hora (e só nos idosos), escolha do limiar. |
| `app/queda/referencia.py` | Modelo de referência (não é a rede do projeto): a régua que a LSTM precisa vencer, e que roda sem TensorFlow. |
| `app/queda/detector.py` | Carrega o modelo exportado e recusa modelo treinado com outro pré-processamento. |
| `app/queda/receptor.py` | Buffer por relógio; avalia uma janela a cada 0,5 s; um alerta por queda. |
| `app/queda/alertas.py` | Tabelas `dispositivos` e `alertas_queda`; ciclo pendente → enviado → confirmado/falso. |
| `app/queda/servico.py` | O que a API faz com cada lote. Testável sem subir a API. |
| `app/routes/sensor.py` | As rotas HTTP, protegidas por `QUEDA_TOKEN`. |
| `notebooks/treino_detector_queda.ipynb` | Treino da LSTM no Colab, quality gate, MLflow e exportação. |
| `scripts/treinar_referencia.py` | Treina e exporta o modelo de referência em segundos. |
| `scripts/simular_relogio.py` | Faz o papel do relógio: manda uma gravação para a API em tempo real. |
| `tests/test_queda.py` | Testes do encanamento inteiro, sem TensorFlow e sem dataset. |

## 3. Passo a passo

### 3.1 Testar o ciclo sem relógio e sem a LSTM (10 minutos)

Da raiz do projeto:

```bash
pip install -r requirements.txt
python -m pytest tests/test_queda.py -q           # todos devem passar
python -m scripts.treinar_referencia               # cria modelos/queda/ com a referência
python -m uvicorn app.main:app --port 8000          # deve aparecer "detector de quedas carregado"
```

Em outro terminal, vincule um relógio de mentira a um grupo. O ID do grupo aparece no terminal do bot (`ID do grupo: ...@g.us`) quando alguém manda um comando nele:

```bash
curl -X POST http://localhost:8000/dispositivos -H "Content-Type: application/json" \
  -d '{"dispositivo": "relogio-demo", "grupo": "SEU_GRUPO@g.us", "pessoa_idosa": "Dona Helena"}'
```

Simule uma queda e uma caminhada de pessoas do **teste** (que o modelo nunca viu):

```bash
python -m scripts.simular_relogio app/rede-neural/dataset/F01/U03_R01_accel.csv   # deve alertar
python -m scripts.simular_relogio app/rede-neural/dataset/D01/U03_R01_accel.csv   # não deve alertar
```

Com o bot no ar (`cd whatsapp-bot && node bot.js`), o alerta chega no grupo em até 5 s, seguido da orientação do Guia. Respondam `!queda ok` ou `!queda falso` e confiram em `http://localhost:8000/alertas/resumo`.

### 3.2 Gravar dados com o Apple Watch

No iPhone, instale o **Sensor Logger** e o app companheiro no relógio. Na tela de sensores, ligue só **Wrist Motion** (e, se quiserem, frequência cardíaca). Frequência: 50 ou 100 Hz.

Protocolo sugerido (anotem num papel quem gravou o quê):

- **Atividades** (D01–D11, mesmos códigos do WEDA — lista no notebook): todos do grupo, 3 repetições cada. Idosos da família podem gravar **só** atividades do dia a dia, com consentimento e sem nenhum risco.
- **Quedas** (F01–F08): **só adultos jovens, sobre colchão ou colchonete**, com alguém ao lado.
- Relógio no pulso **esquerdo**, como a maioria usa (os sinais não dependem do pulso, mas é bom manter o padrão).

Exporte cada gravação como CSV compactado e guarde no Google Drive, uma pasta por gravação: `gravacoes_apple_watch/F01_U40_R01/WristMotion.csv`. Usuário começando com `I` (ex.: `I01`) é marcado como idoso.

### 3.3 Treinar a LSTM no Colab

Abra `notebooks/treino_detector_queda.ipynb` no Colab e rode as células em ordem. Ele:

1. clona o repositório e monta o dataset com `app/queda/` (o mesmo código da API);
2. treina a referência e a LSTM;
3. escolhe o limiar **na validação** e mede **no teste**;
4. aplica o **quality gate** (≥ 90% das quedas detectadas, não pior que a referência);
5. registra no MLflow e baixa `modelo_queda.zip` + `mlruns.zip`.

Descompacte `modelo_queda.zip` em `modelos/queda/` (substituindo a referência) e instale o TensorFlow na versão que o notebook mostrou: `pip install tensorflow-cpu==<versão>`. Ao subir, a API deve mostrar `detector de quedas carregado: lstm ...`. `GET /sensor/situacao` mostra a versão e as métricas do modelo carregado.

### 3.4 Ligar o relógio de verdade

1. **Token.** No `.env` da API: `QUEDA_TOKEN=<uma senha longa>`. Suba o bot com a mesma variável: `QUEDA_TOKEN=<a mesma> node bot.js`.
2. **Endereço público.** O iPhone precisa alcançar a API. Com o [ngrok](https://ngrok.com/) (roda no Windows): `ngrok http 8000` → anote a URL `https://....ngrok-free.app`.
3. **Descobrir o formato.** Suba a API com `QUEDA_CAPTURA=1`. No Sensor Logger, ative o streaming por HTTP com a URL `https://<ngrok>/sensor/sensorlogger?token=<token>&dispositivo=relogio-helena` e grave alguns segundos. Os lotes crus ficam em `dados/capturas/`. Confiram que os itens têm `"name"` com "wrist" e os campos `gravityX`, `accelerationX`, `rotationRateX`. Se o formato for outro, ajuste só `servico.extrair_amostras()`. Depois **desliguem a captura** (é dado de saúde).
4. **Vincular** `relogio-helena` ao grupo (o `curl` do item 3.1).
5. **Ensaiar.** Uma pessoa jovem simula uma queda no colchão com o relógio; o alerta deve chegar ao grupo.

## 4. Como saber se funciona

| Pergunta | Onde se vê |
| --- | --- |
| O encanamento está certo? | `pytest tests/test_queda.py` |
| A rede detecta quedas de quem ela nunca viu? | notebook, seção 6: `recall_quedas` no teste |
| Quantos alarmes falsos o grupo receberia? | `alarmes_falsos_por_hora_idosos` no teste |
| A LSTM vale mais que um modelo simples? | notebook, tabela referência × LSTM |
| Funciona no Apple Watch, não só no WEDA? | notebook, linha "Só Apple Watch" (precisa de gravações do grupo no teste) |
| Funciona em uso real? | `GET /alertas/resumo`: confirmados × falsos, a partir das respostas `!queda` |

Resultado de referência neste repositório (modelo de referência, teste com 6 pessoas que ele nunca viu, 75 quedas): **97% das quedas detectadas**. Os alarmes falsos vêm quase todos de bater a mão na mesa, pular e tropeçar sem cair; andar, subir escada e sentar não geraram nenhum. Leiam "alarmes falsos por hora" com cuidado: as atividades do WEDA foram escolhidas para confundir e a amostra é de cerca de 0,4 h.

## 5. MLOps

- **Versão do modelo**: `config_queda.json` guarda versão, data, limiar, métricas do teste e versões das bibliotecas; cada alerta grava a `versao_modelo` que o gerou.
- **Experimentos**: MLflow no notebook (parâmetros, métricas, tag do quality gate).
- **Quality gate**: o notebook não exporta um modelo que não passe nos critérios.
- **Contrato treino ↔ produção**: o detector recusa um modelo treinado com outra frequência, janela ou conjunto de sinais.
- **Feedback**: cada `!queda falso` é um erro rotulado pela família. No retreino, junte as gravações do grupo e compare a nova versão com a anterior no mesmo teste.

## 6. Limitações e ética

- **Não substitui a detecção de quedas do próprio Apple Watch**, que deve continuar ligada no relógio da pessoa idosa. O alerta diz isso.
- **O iPhone precisa estar por perto** com o Sensor Logger gravando: o relógio guarda poucos minutos sozinho. Serve para MVP e demonstração, não para uso contínuo.
- **Quedas simuladas por adultos jovens** não representam bem quedas reais de idosos. Isso vale para o WEDA e para as gravações do grupo, e deve aparecer na apresentação.
- **Dado de saúde (LGPD, CLAUDE.md §8)**: o sinal do sensor fica só na memória, por poucos segundos; o banco guarda probabilidade, horário e status. Logs só com metadados. A rota é protegida por token. A pessoa idosa precisa concordar em usar o relógio para isso, e pode desligar o streaming quando quiser.
- **Não é diagnóstico**: o alerta é "possível queda, alguém pode verificar?", e a orientação vem do Guia, com página citada.

## 7. Decisão a registrar no CLAUDE.md (quando o grupo confirmar)

> **Rede neural: detector de quedas com Apple Watch** (decisão de __/11/2026). LSTM binária sobre janelas de 2,5 s de 4 sinais invariantes à orientação (WEDA-FALL + gravações do grupo pelo Sensor Logger), integrada por `POST /sensor/sensorlogger`, com alerta no grupo, orientação do Guia e retorno `!queda ok/falso`. Atende à "rede neural simples" e ao MLOps da §9.
