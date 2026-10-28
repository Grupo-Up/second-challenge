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

O bot repassa a mensagem para a API, que roda as duas tarefas do agente em sequência:

```text
bot.js  ──►  api.py  ──►  TAREFA 1  ──►  TAREFA 2  ──►  resposta no grupo
            (HTTP)       extrai o        escreve a
                         compromisso     resposta
```

**Tarefa 1 — `extrair`.** Lê a mensagem e devolve um JSON estruturado. Não preenche nada por dedução: o que a mensagem não disser fica nulo.

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

**Entre as duas, a fusão.** O sistema guarda o compromisso pendente de cada grupo. Quando chega mensagem nova, o Python junta o que já sabia com o que ela trouxe — campo vazio na mensagem nova não apaga o que estava lá.

É o que faz a conversa funcionar:

```text
"a vo Helena tem consulta quinta as 15h"   →  "quem podera acompanhar?"
"eu levo ela"                              →  reconhece a consulta anterior
                                              e pede o nome de quem acompanha
```

**Tarefa 2 — `responder`.** Recebe só o JSON fundido — nunca a mensagem original — e escreve a resposta ao grupo, resumindo o que foi entendido e perguntando o que falta.

```text
Foi identificada uma consulta de cardiologia para Dona Helena
em 29/10 as 15:00, na clinica do centro.
Quem podera acompanha-la nesse dia?
```

Depois de cada tarefa roda um **guardrail** — código Python determinístico, não IA — que rejeita JSON malformado, data no passado e qualquer resposta que afirme ter agendado algo. Detalhes em [`ARQUITETURA.md`](ARQUITETURA.md) §2, §3 e §4.

> **Um agente nesta etapa.** O segundo — o coordenador que cria eventos na agenda — entra quando houver integração com calendário.

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

Depois, num grupo: `!ping` testa a conexão, `!agenda <mensagem>` aciona o agente.

**Testando com o próprio número?** O bot ignora as próprias mensagens por padrão. Suba com `RESPONDER_PROPRIAS=1 node bot.js`.

**Sem WhatsApp:** chame a API direto com `curl` — ela devolve o compromisso estruturado junto com a resposta. Repetindo com o mesmo `grupo_id`, a memória entra em jogo.

**Mexeu nos `.jsonc`?** `./.venv/Scripts/python.exe verificar.py` confere a fiação em um segundo, sem gastar chamada de LLM.

Cola rápida com todos os comandos: [`COMANDOS.md`](COMANDOS.md). Explicação de por que cada coisa funciona assim: [`ARQUITETURA.md`](ARQUITETURA.md) §7 e §8.

> **Rode a API com um worker só.** A memória é um dicionário no processo; `--workers N` com N>1 daria um por processo, e mensagens do mesmo grupo cairiam em lugares diferentes. Vale até o SQLite entrar.

---

## Os arquivos

### Código que roda em produção

| Arquivo | O que faz |
| --- | --- |
| `crew_extrair.jsonc` | **A configuração da tarefa 1.** Prompt da extração e qual guardrail a valida. |
| `crew_responder.jsonc` | **A configuração da tarefa 2.** Prompt da resposta ao grupo e seu guardrail. |
| `agents/assistente_de_compromissos.jsonc` | A persona do agente — `role`, `goal`, `backstory` — e qual LLM ele usa. |
| `agentes.py` | A LLM compartilhada, o carregamento das crews, a fusão entre elas e `processar()`, a função que todo o resto chama. |
| `compromisso.py` | Modelo Pydantic do compromisso, os guardrails e a regra de fusão. Código determinístico, sem LLM — é o que impede o sistema de inventar dado, apagar dado confirmado ou mentir sobre agendamento. |
| `memoria.py` | O compromisso pendente de cada grupo. Dicionário em memória nesta etapa; SQLite é o próximo passo. |
| `api.py` | Servidor FastAPI. Expõe `POST /agente`, que recebe a mensagem e devolve resposta, compromisso e campos faltantes. |
| `whatsapp-bot/bot.js` | Bot em Node com Baileys. Escuta os grupos, reconhece o comando `!agenda`, chama a API e publica a resposta. |

### Teste

| Arquivo | O que faz |
| --- | --- |
| `verificar.py` | Teste de fiação, **sem gastar chamada de LLM**. Roda em um segundo e não participa do fluxo de produção. |

Pega falhas que não levantam exceção: guardrail virando `LLMGuardrail`, crew compartilhada entre pedidos, memoização reintroduzida, placeholder sumindo de um prompt, LLM perdendo `max_tokens`. Vale rodar a cada alteração nos `.jsonc` e depois de atualizar o CrewAI.

Para testar o comportamento — o que o agente entendeu e respondeu — use o `curl` do `POST /agente`: ele devolve o JSON estruturado junto com a resposta.

### Documentação

| Arquivo | O que é |
| --- | --- |
| `CLAUDE.md` | Visão do produto: problema, escopo, requisitos acadêmicos, privacidade, decisões tomadas e pendentes. Fonte de verdade do projeto. |
| `ARQUITETURA.md` | Como o sistema funciona por dentro: as duas tarefas em detalhe, os guardrails, o que ainda não existe, documentação do CrewAI. |
| `COMANDOS.md` | Cola rápida: como ligar a API e o bot, testar sem WhatsApp, e o que checar quando nada acontece. |
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
| Orquestração de agentes | CrewAI 1.15.28, formato JSONC (`crew*.jsonc` + `agents/`) |
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

**Funciona hoje:** interpretação da mensagem, extração estruturada com validação, detecção de dado faltante, **memória entre mensagens do mesmo grupo** — "eu levo ela" completa a consulta combinada antes — e resposta ao grupo pedindo o que falta.

**Ainda não existe:** o segundo agente e a gravação em agenda, detecção de duplicidade e cancelamento, mais de um compromisso pendente por grupo, memória que sobreviva a reiniciar o servidor, rede neural própria, autorização de acesso, base de conhecimento e MLOps. Lista completa com referências ao `CLAUDE.md` em [`ARQUITETURA.md`](ARQUITETURA.md) §9.

O requisito acadêmico de **dois agentes de IA colaborando** (`CLAUDE.md` §9) fica em aberto até o coordenador de agenda existir — duas tarefas do mesmo agente não o cumprem.
