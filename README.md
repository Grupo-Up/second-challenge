# Agentes de IA para apoio aos cuidados de idosos

Dois agentes de IA que leem as combinações feitas num grupo familiar de WhatsApp e transformam o que foi dito em um compromisso organizado — consulta, exame, retorno — apontando o que ficou faltando e quem precisa responder.

O objetivo é reduzir esquecimentos e evitar que informações importantes se percam no meio das mensagens, sem substituir a confirmação humana nem a autonomia da pessoa idosa.

Projeto acadêmico. Visão completa do produto em [`CLAUDE.md`](CLAUDE.md); funcionamento interno em [`ARQUITETURA.md`](docs/ARQUITETURA.md).

---

## Como funciona

Alguém escreve no grupo:

```text
!agenda a vo Helena tem consulta no cardiologista quinta-feira as 15h, na clinica do centro
```

O bot repassa a mensagem para a API, que roda os dois agentes em sequência:

```text
bot.js  ──►  app/main.py  ──►  AGENTE 1  ──►  AGENTE 2  ──►  resposta no grupo
            (HTTP)            extrai o        escreve a
                              compromisso     resposta
```

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

**Agente 2 — Coordenador.** Recebe só o JSON — nunca a mensagem original — e escreve a resposta ao grupo, resumindo o que foi entendido e perguntando o que falta.

```text
O compromisso e uma consulta de cardiologia para Dona Helena,
dia 29 de outubro de 2026, as 15:00, na clinica do centro.
Quem podera acompanha-la nesse dia?
```

O campo `classificacao` decide a resposta. Em `cuidado`, o resumo acima. Em `fora_do_escopo` — uma reunião de trabalho, um aniversário — o assistente responde que aquilo fica fora do que ele acompanha. Em `conversa`, que nenhum compromisso foi identificado.

Entre os dois agentes e depois deles rodam **guardrails** — código Python determinístico, não IA — que rejeitam JSON malformado, data no passado e qualquer resposta que afirme ter agendado algo. Detalhes em [`ARQUITETURA.md`](docs/ARQUITETURA.md) §2 e §3.

> **Nada é gravado em agenda ainda.** Não há integração com Google Calendar ou equivalente. Nesta etapa o sistema apenas interpreta e organiza a conversa.

---

## Instalação

**Pré-requisitos:** Python 3.12, Node.js 22+, uma conta no [Groq](https://console.groq.com) para a chave de API.

```bash
# 1. Ambiente Python
python -m venv .venv
./.venv/Scripts/python.exe -m pip install crewai fastapi uvicorn python-dotenv json-repair pydantic

# 2. Dependências do bot
cd whatsapp-bot && npm install && cd ..
```

Crie um `.env` na raiz:

```ini
GROQ_API_KEY=sua_chave_aqui
```

> O `.env` **não vai para o repositório**. Cada pessoa cria o seu.

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

Depois, num grupo: `!ping` testa a conexão, `!agenda <mensagem>` aciona os agentes.

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
│   │   ├── interprete.py    # agente 1
│   │   └── coordenador.py   # agente 2
│   └── crews/crew.py        # a LLM, as duas tarefas e a Crew
├── docs/ARQUITETURA.md
├── whatsapp-bot/bot.js
├── CLAUDE.md
└── README.md
```

### Código

| Arquivo | O que faz |
| --- | --- |
| `app/crews/crew.py` | **O coração.** Define a LLM, as duas tarefas e a Crew que liga os agentes. `processar()` é a função que todo o resto chama. |
| `app/agents/interprete.py` | Agente 1: papel, objetivo e história de quem lê a mensagem e extrai o compromisso. |
| `app/agents/coordenador.py` | Agente 2: papel, objetivo e história de quem responde ao grupo. |
| `app/compromisso.py` | Modelo Pydantic do compromisso e os guardrails. Código determinístico, sem LLM — é o que impede o sistema de inventar dado ou mentir sobre agendamento. |
| `app/routes/agente.py` | `POST /agente`, que recebe a mensagem e devolve resposta, compromisso e campos faltantes. |
| `app/main.py` | Sobe o FastAPI e inclui o router. É o alvo do `uvicorn`. |
| `whatsapp-bot/bot.js` | Bot em Node com Baileys. Escuta os grupos, reconhece o comando `!agenda`, chama a API e publica a resposta. |

Agentes e tarefas ficam em arquivos separados de propósito: **quem é o agente** muda pouco, **o que se pede a ele** muda a cada ajuste de regra.

### Documentação

| Arquivo | O que é |
| --- | --- |
| `CLAUDE.md` | Visão do produto: problema, escopo, requisitos acadêmicos, privacidade, decisões tomadas e pendentes. Fonte de verdade do projeto. Fica na raiz porque é lido automaticamente pelo Claude Code. |
| `docs/ARQUITETURA.md` | Como o sistema funciona por dentro: os agentes em detalhe, os guardrails, o que ainda não existe, documentação do CrewAI. |
| `README.md` | Este arquivo. |

### Não versionado

| Caminho | Por quê |
| --- | --- |
| `.env` | Contém a `GROQ_API_KEY`. |
| `whatsapp-bot/auth/` | Credenciais da sessão de WhatsApp pareada. Quem tiver esses arquivos acessa a conta. |
| `.venv/`, `whatsapp-bot/node_modules/` | Dependências, reinstaláveis. |
| `.crewai/`, `__pycache__/` | Artefatos de execução, regerados sozinhos. |

---

## Stack

| Camada | Tecnologia |
| --- | --- |
| Orquestração de agentes | CrewAI 1.15.28 |
| Modelo | `gpt-oss-20b` hospedado no Groq |
| API | FastAPI + uvicorn |
| WhatsApp | Baileys 7.0.0-rc14 (Node) |
| Validação | Pydantic + regex, em `compromisso.py` |

---

## Privacidade

As conversas podem conter informações de saúde. O projeto trata LGPD e minimização de dados como requisito desde o início (`CLAUDE.md` §8).

- O conteúdo das mensagens **não vai para os logs**. O terminal registra apenas metadados: se identificou compromisso e quais campos faltam. A variável `DEBUG_AGENTES=1` liga o log completo — **use só em desenvolvimento, com dados fictícios**.
- O bot processa apenas mensagens de grupo que comecem com `!agenda`. Conversa comum é descartada sem chegar à API.
- O CrewAI envia traços de execução para `app.crewai.com` por padrão. Isso ainda **não foi desativado** — pendência aberta, relevante para o item acima.

---

## Status

Protótipo funcional. Demonstrável com perfis fictícios.

**Funciona hoje:** interpretação da mensagem, extração estruturada com validação, detecção de dado faltante, resposta ao grupo pedindo o que falta.

**Ainda não existe:** gravação em agenda, memória entre mensagens, detecção de duplicidade, rede neural própria, autorização de acesso, base de conhecimento e MLOps. Lista completa com referências ao `CLAUDE.md` em [`ARQUITETURA.md`](docs/ARQUITETURA.md) §8.
