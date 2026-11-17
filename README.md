# Agentes de IA para apoio aos cuidados de idosos

Três agentes de IA que leem as combinações feitas num grupo familiar de WhatsApp e transformam o que foi dito em um compromisso organizado — consulta, exame, retorno — apontando o que ficou faltando, gravando na agenda quando o grupo confirma, e respondendo dúvidas de cuidado a partir do Guia do Cuidador.

O objetivo é reduzir esquecimentos e evitar que informações importantes se percam no meio das mensagens, sem substituir a confirmação humana nem a autonomia da pessoa idosa.

Projeto acadêmico. Visão completa do produto em [`CLAUDE.md`](CLAUDE.md); funcionamento interno em [`ARQUITETURA.md`](docs/ARQUITETURA.md).

---

## Como funciona

Alguém escreve no grupo:

```text
!agenda a vo Helena tem consulta no cardiologista quinta-feira as 15h, na clinica do centro
```

### Comandos

| Comando | Para quê |
| --- | --- |
| `!agenda <informação>` | informa consulta, exame, horário, local, quem acompanha ou remarcação |
| `!compromisso` | mostra o que está combinado e o que já foi gravado — sem IA, lê o estado e o banco |
| `!andamento <pergunta>` | pergunta em linguagem livre **sobre o compromisso em aberto** |
| `!duvida <pergunta>` | pergunta **sobre o cuidado da pessoa idosa**, respondida pelo Guia do Cuidador |
| `!ajuda` | lista os comandos; responde também a qualquer `!` desconhecido |
| `!ping` | testa se o bot está escutando o grupo |

`!andamento` e `!duvida` são parecidos no formato e diferentes no assunto. *"Quem vai levar a vó?"* é `!andamento` — a resposta está no que o grupo combinou. *"Como dar banho em idoso acamado?"* é `!duvida` — a resposta está no Guia.

Mensagem sem `!` não é processada — conversa comum nem chega à API.

O bot repassa a mensagem para a API, que roda um grafo de agentes:

```text
bot.js  ──►  app/main.py  ──►  AGENTE 1  ──►  guardrail ──┬──►  AGENTE 2  ──►  resposta no grupo
            (HTTP)            extrai o                    │    escreve a
                              compromisso                 │    resposta
                                                          └──►  resposta fixa, sem IA
                                                               (não é cuidado)
```

O caminho depois do Agente 1 depende do que ele extraiu. Só mensagem de cuidado chega ao Agente 2.

**Agente 1 — Intérprete.** Lê a mensagem e devolve um JSON estruturado. Não preenche nada por dedução: o que a mensagem não disser fica nulo.

```json
{
  "tipo": "consulta",
  "pessoa_idosa": "Dona Helena",
  "especialidade": "cardiologia",
  "data": "2026-10-29",
  "horario": "15:00",
  "local": "clinica do centro",
  "responsavel": null,
  "classificacao": "cuidado"
}
```

**Memória do grupo.** O compromisso é montado ao longo da conversa, não numa mensagem só. "A vó Helena tem consulta amanhã", depois "é com cardiologista, às 15h", depois "eu levo ela" — o sistema soma as três no mesmo compromisso, e resolve o "eu" pelo nome de quem escreveu. Cada grupo tem seu próprio thread, identificado pelo JID. Se uma mensagem **contradiz** o que já estava combinado, nada é sobrescrito: o assistente pergunta se é remarcação ou compromisso diferente — e entende a resposta. "Sim, foi remarcado" aplica a data nova; "não, é outro exame" mantém a antiga.

Para isso o sistema guarda as **últimas 12 falas** do grupo, mensagens e respostas. É o que permite entender "ela", "essa consulta" e "sim, foi". Mais que isso não é guardado, e tudo some quando o compromisso é concluído.

**Agente 2 — Coordenador.** Recebe só o JSON acumulado — nunca a mensagem original — e escreve a resposta ao grupo, resumindo o que foi entendido e perguntando o que falta.

```text
O compromisso e uma consulta de cardiologia para Dona Helena,
dia 29 de outubro de 2026, as 15:00, na clinica do centro.
Quem podera acompanha-la nesse dia?
```

O campo `classificacao` decide o caminho no grafo. Em `cuidado`, o Agente 2 escreve o resumo acima. Em `fora_do_escopo` — uma reunião de trabalho, um aniversário — e em `conversa`, a resposta é um texto fixo, sem chamar LLM nenhuma: não há o que resumir nem o que perguntar.

**A agenda.** O Agente 2 tem uma ferramenta que grava o compromisso num banco. Quem decide chamá-la é ele, no meio da resposta — mas a gravação é verificada em código antes de acontecer:

| Verificação | Sem isso |
| --- | --- |
| tipo, pessoa idosa, data e horário presentes | recusa |
| **alguém aceitou acompanhar** | recusa e manda perguntar ao grupo |
| data válida e no futuro | recusa |
| mesma consulta já ativa | recusa como duplicata |

Então a consulta só entra na agenda depois que alguém do grupo disse "eu levo ela". O sistema não escolhe quem acompanha ([`CLAUDE.md`](CLAUDE.md) §6).

Cancelar marca o registro como `cancelado` em vez de apagar: o histórico do que a família combinou não some porque alguém errou o número.

**Agente 3 — Consultor do Guia.** Responde `!duvida` a partir do *Guia do Cuidador*, um PDF de 250 páginas indexado localmente. É o único agente com busca própria: ele decide consultar o Guia antes de responder, e cita a página de onde tirou cada informação.

```text
Para prevenir quedas: instale corrimãos e barras de apoio no banheiro
(Página 220), use tapetes antiderrapantes (Página 220) e mantenha o
piso limpo e seco (Página 221).
```

Se o Guia não cobre a pergunta, ele diz que não sabe — e nunca indica medicamento ou dose.

**Guardrails.** Antes e depois de cada agente roda código Python determinístico, não IA, que rejeita JSON malformado, data no passado, resposta que afirme ter gravado algo sem a ferramenta confirmar, e orientação de saúde sem citar a página. No grafo eles são nós: quando reprovam, a aresta volta ao agente com o motivo. Detalhes em [`ARQUITETURA.md`](docs/ARQUITETURA.md) §2, §3 e §4.

> **Ainda não é um calendário de verdade.** O compromisso é gravado numa tabela do projeto, não na agenda que a pessoa abre no celular. Google Calendar e Outlook continuam em aberto.

---

## Instalação

**Pré-requisitos:** Python 3.12, Node.js 22+, uma conta no [Groq](https://console.groq.com) para a chave de API.

```bash
# 1. Ambiente Python
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt

# 2. Dependências do bot
cd whatsapp-bot && npm install && cd ..
```

Crie um `.env` na raiz:

```ini
GROQ_API_KEY=sua_chave_aqui
```

> O `.env` **não vai para o repositório**. Cada pessoa cria o seu.

**O download é grande.** O Agente 3 roda o modelo de embeddings na própria máquina, então o `requirements.txt` traz `torch` e `sentence-transformers` — cerca de 1 GB, mais o modelo em si na primeira execução. A linha `--extra-index-url` no topo do arquivo é o que evita baixar a versão com CUDA, de vários GB.

### O banco da agenda

Por padrão **não precisa instalar nada**: os compromissos vão para `dados/agenda.sqlite`, e o SQLite já vem no Python. A tabela é criada sozinha na primeira gravação.

Para usar PostgreSQL em vez disso — é o que o `compose.yml` sobe:

```bash
docker compose up -d
./.venv/Scripts/python.exe -m pip install "psycopg[binary]"
```

e no `.env`:

```ini
DATABASE_URL=postgresql://agenda_app:agenda_dev_password@localhost:5432/agenda
```

O código é o mesmo nos dois casos. Quem escolhe é a presença da `DATABASE_URL`, lida a cada conexão em `app/tools/banco.py` — então dá para alternar sem mexer em nada.

---

## Como rodar

Dois processos, em dois terminais. Comandos em Bash — no PowerShell troque `/` por `\`.

**Terminal 1 — API dos agentes:**

```bash
./.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000
```

Confirme com `curl http://localhost:8000/saude` → `{"status":"ok"}`

**Terminal 2 — bot do WhatsApp:**

```bash
cd whatsapp-bot
node bot.js
```

Na primeira execução aparece um QR code — leia com o WhatsApp do celular. A sessão fica salva em `whatsapp-bot/auth/`.

Depois, num grupo: `!ping` testa a conexão e `!ajuda` lista os comandos.

**Testando com o próprio número?** O bot ignora as próprias mensagens por padrão. Suba com `RESPONDER_PROPRIAS=1 node bot.js`.

**Sem WhatsApp:** com a API no ar, chame direto:

```bash
curl -X POST http://localhost:8000/agente \
  -H "Content-Type: application/json" \
  -d '{"mensagem": "a vo Helena tem consulta no cardiologista quinta as 15h"}'
```

Passo a passo completo e solução de problemas: [`ARQUITETURA.md`](docs/ARQUITETURA.md) §6 e §7.

---

## Os arquivos

```text
challenge-2/
├── app/
│   ├── main.py              # sobe o FastAPI e registra as rotas
│   ├── compromisso.py       # modelo de dados e guardrails — sem IA
│   ├── routes/agente.py     # POST /agente e GET /saude
│   ├── agents/
│   │   ├── interprete.py    # agente 1 — quem ele é
│   │   ├── coordenador.py   # agente 2 — quem ele é
│   │   └── RAG.py           # agente 3 — quem ele é, mais a busca no Guia
│   ├── tools/
│   │   ├── agenda.py        # a ferramenta do agente 2 — grava os compromissos
│   │   └── banco.py         # SQLite ou PostgreSQL, pela DATABASE_URL
│   └── graph/
│       ├── estado.py        # o estado que atravessa o grafo
│       ├── prompts.py       # o que se pede a cada agente
│       ├── nos.py           # os nós: agentes, guardrails, fusão e roteamento
│       └── grafo.py         # monta o grafo, o checkpointer e processar()
├── arquivos/                # o PDF do Guia do Cuidador
├── dados/                   # fora do repositório
│   ├── conversas.sqlite     #   estado das conversas
│   └── agenda.sqlite        #   os compromissos gravados
├── compose.yml              # PostgreSQL, alternativa ao SQLite
├── docs/ARQUITETURA.md
├── whatsapp-bot/bot.js
├── CLAUDE.md
└── README.md
```

### Código

| Arquivo | O que faz |
| --- | --- |
| `app/graph/grafo.py` | **O coração.** Monta o grafo: nós, arestas e o roteamento. `processar()` é a função que todo o resto chama. |
| `app/graph/nos.py` | Cada nó do grafo: os três agentes chamando a LLM, os guardrails e as funções que decidem o caminho. |
| `app/graph/prompts.py` | O que se pede a cada agente, mais as respostas fixas que não passam por LLM. |
| `app/graph/estado.py` | O `EstadoGrupo`: tudo que o grafo lê e escreve durante uma mensagem. |
| `app/agents/interprete.py` | Agente 1: papel, objetivo e história de quem lê a mensagem e extrai o compromisso. |
| `app/agents/coordenador.py` | Agente 2: papel, objetivo e história de quem responde ao grupo e grava na agenda. |
| `app/agents/RAG.py` | Agente 3: quem ele é, mais a leitura do PDF, o índice e a busca que ele usa. |
| `app/tools/agenda.py` | A ferramenta do Agente 2: criar, consultar, alterar e cancelar compromissos. Valida tudo antes de gravar. |
| `app/tools/banco.py` | Escolhe SQLite ou PostgreSQL pela `DATABASE_URL`. Único arquivo que sabe que existem dois. |
| `app/compromisso.py` | Modelo Pydantic do compromisso e os guardrails. Código determinístico, sem LLM — é o que impede o sistema de inventar dado ou mentir sobre agendamento. |
| `app/routes/agente.py` | `POST /agente`, que recebe a mensagem e devolve resposta, compromisso e campos faltantes. |
| `app/main.py` | Sobe o FastAPI e inclui o router. É o alvo do `uvicorn`. |
| `whatsapp-bot/bot.js` | Bot em Node com Baileys. Escuta os grupos, reconhece o comando `!agenda`, chama a API e publica a resposta. |

`app/agents/` e `app/graph/prompts.py` ficam separados de propósito: **quem é o agente** muda pouco, **o que se pede a ele** muda a cada ajuste de regra.

### Documentação

| Arquivo | O que é |
| --- | --- |
| `CLAUDE.md` | Visão do produto: problema, escopo, requisitos acadêmicos, privacidade, decisões tomadas e pendentes. Fonte de verdade do projeto. Fica na raiz porque é lido automaticamente pelo Claude Code. |
| `docs/ARQUITETURA.md` | Como o sistema funciona por dentro: o grafo, os agentes em detalhe, os guardrails, o que ainda não existe, documentação do LangGraph. |
| `README.md` | Este arquivo. |

### Não versionado

| Caminho | Por quê |
| --- | --- |
| `.env` | Contém a `GROQ_API_KEY`. |
| `whatsapp-bot/auth/` | Credenciais da sessão de WhatsApp pareada. Quem tiver esses arquivos acessa a conta. |
| `dados/` | Estado das conversas e os compromissos gravados, em SQLite. Contém informação de saúde. |
| `.venv/`, `whatsapp-bot/node_modules/` | Dependências, reinstaláveis. |
| `__pycache__/` | Artefatos de execução, regerados sozinhos. |

---

## Stack

| Camada | Tecnologia |
| --- | --- |
| Orquestração de agentes | LangGraph 1.2.20 + langchain-groq 1.1.3 |
| Modelo | `gpt-oss-20b` hospedado no Groq |
| Base de conhecimento | `multilingual-e5-base` + `sentence-transformers`, rodando local |
| Agenda | SQLite (padrão) ou PostgreSQL 16 pelo `compose.yml` |
| API | FastAPI + uvicorn |
| WhatsApp | Baileys 7.0.0-rc14 (Node) |
| Validação | Pydantic + regex, em `compromisso.py` |

---

## Privacidade

As conversas podem conter informações de saúde. O projeto trata LGPD e minimização de dados como requisito desde o início (`CLAUDE.md` §8).

- O conteúdo das mensagens **não fica gravado em disco**. O estado da conversa guarda o compromisso estruturado, não o texto que alguém escreveu; e quando o compromisso é concluído, o thread daquele grupo é apagado inteiro. `RETER_HISTORICO=1` desliga as duas coisas para inspecionar o grafo passo a passo — **use só em desenvolvimento, com dados fictícios**. Detalhes em [`ARQUITETURA.md`](docs/ARQUITETURA.md) §1a.
- **O compromisso gravado fica.** A conversa é apagada quando o compromisso encerra, mas o registro na agenda permanece — é ele que o `!compromisso` mostra depois. São dados de saúde num banco local: `dados/` está fora do repositório, e com PostgreSQL ficam no container.
- O conteúdo das mensagens **não vai para os logs**. O terminal registra apenas metadados: se identificou compromisso, quais campos faltam e se a agenda foi chamada — nunca o que foi gravado. A variável `DEBUG_AGENTES=1` liga o log completo — **use só em desenvolvimento, com dados fictícios**.
- As perguntas do `!duvida` **não saem da máquina** para serem indexadas: o modelo de embeddings roda local. Só a pergunta em si vai ao Groq, como nos outros comandos.
- O bot processa apenas mensagens de grupo que comecem com um comando. Conversa comum é descartada sem chegar à API.
- Não existe ainda um comando para a família apagar os próprios dados. O `CLAUDE.md` §8 pede isso; hoje só dá para apagar o arquivo à mão. Pendência aberta.
- O LangGraph não envia traços para fora por padrão. O rastreamento no LangSmith só liga com `LANGSMITH_TRACING=true` no ambiente — e, se for ligado, passa a enviar o conteúdo das mensagens para um serviço externo. **Não ligue com dados reais.** (A versão anterior, em CrewAI, enviava traços para `app.crewai.com` por padrão; essa pendência deixou de existir com a migração.)

---

## Status

Protótipo funcional. Demonstrável com perfis fictícios.

**Funciona hoje:** interpretação da mensagem, extração estruturada com validação, acúmulo do compromisso ao longo da conversa do grupo, detecção de contradição, resposta ao grupo pedindo o que falta, gravação na agenda depois que alguém aceita acompanhar, consulta ao que já foi gravado, e dúvidas de cuidado respondidas pelo Guia do Cuidador com a página citada.

**Ainda não existe:** integração com calendário de verdade (Google, Outlook), resolução do conflito pela conversa (o assistente pergunta, mas não há como responder), mais de um compromisso aberto por grupo, rede neural própria, autorização por pessoa e MLOps. Lista completa com referências ao `CLAUDE.md` em [`ARQUITETURA.md`](docs/ARQUITETURA.md) §8.
