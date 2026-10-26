# Agentes de IA para apoio aos cuidados de idosos

Dois agentes de IA que leem as combinações feitas num grupo familiar de WhatsApp e transformam o que foi dito em um compromisso organizado — consulta, exame, retorno — apontando o que ficou faltando e quem precisa responder.

O objetivo é reduzir esquecimentos e evitar que informações importantes se percam no meio das mensagens, sem substituir a confirmação humana nem a autonomia da pessoa idosa.

Projeto acadêmico. Visão completa do produto em [`CLAUDE.md`](CLAUDE.md); funcionamento interno em [`ARQUITETURA.md`](ARQUITETURA.md).

---

## Como funciona

Alguém escreve no grupo:

```text
!agenda a vo Helena tem consulta no cardiologista quinta-feira as 15h, na clinica do centro
```

O bot repassa a mensagem para a API, que roda os dois agentes em sequência:

```text
bot.js  ──►  api.py  ──►  AGENTE 1  ──►  AGENTE 2  ──►  resposta no grupo
            (HTTP)       extrai o        escreve a
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
  "e_compromisso": true
}
```

**Agente 2 — Coordenador.** Recebe só o JSON — nunca a mensagem original — e escreve a resposta ao grupo, resumindo o que foi entendido e perguntando o que falta.

```text
Foi identificada uma consulta de cardiologia para Dona Helena
em 29/10 as 15:00, na clinica do centro.
Quem podera acompanha-la nesse dia?
```

Entre os dois agentes e depois deles rodam **guardrails** — código Python determinístico, não IA — que rejeitam JSON malformado, data no passado e qualquer resposta que afirme ter agendado algo. Detalhes em [`ARQUITETURA.md`](ARQUITETURA.md) §2 e §3.

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
./.venv/Scripts/python.exe -m uvicorn api:app --reload --port 8000
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

**Sem WhatsApp:** `./.venv/Scripts/python.exe two_agents.py` roda três cenários no terminal.

Passo a passo completo e solução de problemas: [`ARQUITETURA.md`](ARQUITETURA.md) §6 e §7.

---

## Os arquivos

### Código que roda em produção

| Arquivo | O que faz |
| --- | --- |
| `agentes.py` | **O coração.** Define os dois agentes, as duas tarefas e a Crew que os liga. `processar()` é a função que todo o resto chama. |
| `compromisso.py` | Modelo Pydantic do compromisso e os guardrails. Código determinístico, sem LLM — é o que impede o sistema de inventar dado ou mentir sobre agendamento. |
| `api.py` | Servidor FastAPI. Expõe `POST /agente`, que recebe a mensagem e devolve resposta, compromisso e campos faltantes. |
| `whatsapp-bot/bot.js` | Bot em Node com Baileys. Escuta os grupos, reconhece o comando `!agenda`, chama a API e publica a resposta. |

### Scripts de demonstração

Rodam os agentes direto no terminal, **sem WhatsApp e sem API**. Nenhum dos dois participa do fluxo de produção — `api.py` não os importa, e apagá-los não afeta o bot.

| Arquivo | O que faz |
| --- | --- |
| `first_agent.py` | Roda **só o Agente 1**, sobre uma mensagem fixa, com `verbose=True`. Mostra o raciocínio do agente e os retries do guardrail. Use quando o defeito está na extração e você não quer esperar o Agente 2. |
| `two_agents.py` | Roda **os dois agentes**, sobre três mensagens fixas: uma completa, uma com dado faltando e uma conversa cotidiana. Imprime o JSON do Agente 1 e a resposta do Agente 2 lado a lado. |

A mensagem de entrada é fixa no código dos dois — para testar outra frase, edite a constante no topo do arquivo.

Servem para três coisas: **isolar defeito** (se `two_agents.py` funciona, o problema está no bot ou na API, não nos agentes), **iterar rápido** em prompts sem subir nada, e **demonstrar** os cenários sem depender de QR code e conexão.

### Documentação

| Arquivo | O que é |
| --- | --- |
| `CLAUDE.md` | Visão do produto: problema, escopo, requisitos acadêmicos, privacidade, decisões tomadas e pendentes. Fonte de verdade do projeto. |
| `ARQUITETURA.md` | Como o sistema funciona por dentro: os agentes em detalhe, os guardrails, o que ainda não existe, documentação do CrewAI. |
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

**Ainda não existe:** gravação em agenda, memória entre mensagens, detecção de duplicidade, rede neural própria, autorização de acesso, base de conhecimento e MLOps. Lista completa com referências ao `CLAUDE.md` em [`ARQUITETURA.md`](ARQUITETURA.md) §8.
