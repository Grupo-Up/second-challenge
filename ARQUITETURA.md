# Arquitetura dos agentes

Como a mensagem do grupo vira uma resposta, quem faz o quê e o que ainda não existe.

Contexto do produto: [`CLAUDE.md`](CLAUDE.md). Este documento descreve **o que está implementado hoje**, não a visão completa.

---

## 1. Visão geral

Quatro arquivos. Só um deles contém agentes.

| Arquivo               | Papel                                                               | É um processo?          |
| --------------------- | ------------------------------------------------------------------- | ----------------------- |
| `whatsapp-bot/bot.js` | Escuta o WhatsApp, reconhece o comando, devolve a resposta ao grupo | Sim — `node bot.js`     |
| `api.py`              | Expõe `POST /agente`, faz a ponte entre o bot e os agentes          | Sim — `uvicorn api:app` |
| `agentes.py`          | Define os dois agentes, as duas tarefas e a Crew                    | Não — módulo            |
| `compromisso.py`      | Modelo de dados e guardrails determinísticos                        | Não — módulo            |

`first_agent.py` e `two_agents.py` são demos de terminal, fora do fluxo do WhatsApp.

### O caminho de uma mensagem

```text
Você digita no grupo:  !agenda a vo Helena tem consulta no cardiologista quinta as 15h
        │
        ▼
bot.js          ← processo Node. Escuta o WhatsApp.
        │          Corta o "!agenda", pega a data de hoje, manda POST
        ▼
api.py          ← processo uvicorn na porta 8000. POST /agente
        │          Chama processar(mensagem, data)
        ▼
agentes.py      ← monta a Crew e roda os DOIS agentes em sequência
        │
        ├─ AGENTE 1 ─► JSON do compromisso
        │                    │
        │                    ▼ (context)
        └─ AGENTE 2 ─► texto da resposta ao grupo
        │
        ▼
api.py devolve {resposta, compromisso, faltantes}
        │
        ▼
bot.js envia o texto da "resposta" no grupo
```

Os agentes **não ficam rodando**. Eles nascem, trabalham e morrem a cada comando — `montar_crew()` (`agentes.py:146`) cria tudo do zero dentro de `processar()`. Isso é proposital: agentes e tarefas do CrewAI guardam o resultado da última execução, então reaproveitar os mesmos objetos misturaria o contexto de conversas diferentes.

---

## 2. Agente 1 — Intérprete de Compromissos

Definido em `criar_interprete()` (`agentes.py:38`), tarefa em `tarefa_interpretar()` (`agentes.py:83`).

- **Entrada:** o texto cru da mensagem + a data de hoje
- **Trabalho:** ler e separar o que foi dito do que só parece provável
- **Saída:** um JSON, nada mais

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

Repare no `responsavel: null`. A mensagem citou a consulta, mas ninguém se ofereceu pra levar. A regra (4) do prompt (`agentes.py:97`) diz: _mencionar uma pessoa não é o mesmo que ela ter aceitado_. Campo vazio é corrigível; campo inventado manda a família pro lugar errado.

O campo `e_compromisso` fica `false` quando a mensagem é conversa cotidiana — "alguém viu o jogo ontem?". Aí todos os outros campos ficam nulos.

### Guardrail `validar_extracao`

Em `compromisso.py:111`. Roda **depois** da LLM e **não é IA** — é código determinístico:

1. Tenta ler o JSON com `json_repair`, que tolera as falhas comuns de LLM: cerca de markdown, vírgula sobrando, aspas trocadas.
2. Valida contra o modelo Pydantic `Compromisso` (`compromisso.py:39`).
3. Checa formato e coerência: data `AAAA-MM-DD`, horário `HH:MM`, **e rejeita data no passado**.
4. Falhou? Devolve `(False, "mensagem de erro")` e o CrewAI **reexecuta o agente** com esse erro no prompt — até 2 vezes (`guardrail_max_retries=2`).
5. Passou? Devolve o JSON normalizado. É exatamente esse texto que o Agente 2 recebe.

É aqui que "quinta-feira" vira `2026-10-29` com segurança: o prompt passa a data de hoje como referência e o guardrail confere que o resultado é uma data real e futura.

---

## 3. Agente 2 — Coordenador de Cuidados

Definido em `criar_coordenador()` (`agentes.py:61`), tarefa em `tarefa_coordenar()` (`agentes.py:116`).

- **Entrada:** o JSON do Agente 1, via `context=[anterior]` (`agentes.py:140`)
- **Trabalho:** resumir o que foi entendido e perguntar o que falta
- **Saída:** um texto curto, até 4 frases, em português

Ele **não vê a mensagem original** — só os dados já extraídos e validados. Isso é de propósito: assim ele não pode "reinterpretar" e reintroduzir um detalhe que o Agente 1 descartou.

```text
Foi identificada uma consulta de cardiologia para Dona Helena
em 29/10 as 15:00, na clinica do centro.
Quem podera acompanha-la nesse dia?
```

Duas obrigações:

- **Pedir o que falta.** Se `data` ou `horario` estão nulos, pergunta. Se não há `responsavel`, pergunta quem pode acompanhar — e **nunca escolhe alguém**.
- **Não mentir sobre agendamento.** Nada foi gravado em agenda nesta etapa.

### Guardrail `validar_resposta`

Em `compromisso.py:155`. Passa um regex procurando "agendei", "marquei", "registrei", "cadastrei", "coloquei na agenda". Achou? Rejeita e manda reescrever.

Existe porque **nada é gravado em agenda nenhuma ainda**. Sem esse guardrail, a LLM diria "pronto, agendei!" — e a família confiaria num evento que não existe. Ver `CLAUDE.md` §4: _nunca informar que agendou se a API de calendário não confirmar a criação_.

---

## 4. `compromisso.py` — a metade sem IA

Os dois agentes compartilham este arquivo. Ele não chama LLM nenhuma: é Python comum, com Pydantic e expressões regulares. Mesma entrada, mesma saída, sempre.

A divisão de responsabilidade entre os dois arquivos é a ideia central do projeto:

> `agentes.py` **pede** para o agente não adivinhar. `compromisso.py` **verifica** que ele não adivinhou.

Pedido é sugestão — um prompt pode ser ignorado por uma LLM num dia ruim. Verificação é garantia.

### O contrato de dados

A classe `Compromisso` (`compromisso.py:39`) declara quais campos existem e de que tipo. Se a LLM inventar um campo ou trocar um tipo, a falha aparece aqui, não três camadas adiante.

```python
OBRIGATORIOS = ("tipo", "pessoa_idosa", "data", "horario")
```

São os quatro campos sem os quais o compromisso não poderá ser agendado mais tarde. `local`, `especialidade` e `responsavel` ficam de fora de propósito: a falta deles não impede o agendamento, só exige uma pergunta ao grupo.

### Os dois guardrails

| Função | Valida a saída de | Rejeita |
| --- | --- | --- |
| `validar_extracao` (`:111`) | Agente 1 | JSON malformado, campo inválido, data fora do formato, **data no passado** |
| `validar_resposta` (`:155`) | Agente 2 | texto que afirme ter agendado, marcado ou registrado |

Ambos devolvem `(True, saida_normalizada)` ou `(False, "explicação do erro")`. No segundo caso o CrewAI **reexecuta o agente** com a explicação no prompt, até 2 vezes.

Exemplo concreto: a LLM interpreta "quinta-feira" como uma data que já passou. O guardrail barra e responde ao agente _"data no passado: 2026-10-22"_. Ele recalcula com essa informação.

Detalhamento de cada um nas seções [§2](#2-agente-1--intérprete-de-compromissos) e [§3](#3-agente-2--coordenador-de-cuidados).

### Utilitários

| Função | Para quê |
| --- | --- |
| `hoje()` | data corrente no fuso de São Paulo — referência para "amanhã", "quinta-feira" |
| `faltantes()` | quais campos obrigatórios ainda estão vazios; usado por `api.py` e pelos demos |
| `interpretar_json()` | lê o JSON da LLM tolerando cerca de markdown, vírgula sobrando e aspas trocadas |

### Por que mora fora do `agentes.py`

Três razões práticas:

1. **Testável sem LLM.** Dá para verificar toda a lógica de validação sem gastar uma chamada à API nem depender da variação de temperatura do modelo.
2. **Um lugar só.** Os dois agentes e os dois demos usam as mesmas regras. Duplicar daria divergência.
3. **Sobrevive à troca de framework.** O arquivo não importa nada do CrewAI. Se o framework de agentes mudar, a parte que impede o sistema de inventar dado atravessa a migração intacta.

---

## 5. Por que dois agentes e não um

Papéis diferentes, falhas diferentes.

| Agente          | Como ele erra                      | O que pega o erro                                        |
| --------------- | ---------------------------------- | -------------------------------------------------------- |
| 1 — Intérprete  | Extrai dado errado, inventa data   | `validar_extracao`: Pydantic + formato + data no passado |
| 2 — Coordenador | Fala demais, promete o que não fez | `validar_resposta`: regex de afirmação de agendamento    |

Um agente único misturaria as duas responsabilidades num prompt só, e qualquer validação teria que adivinhar qual metade falhou. Separando, cada guardrail sabe exatamente o que está checando e o retry reexecuta só a etapa quebrada.

Também atende o requisito acadêmico de **dois agentes de IA colaborando** (`CLAUDE.md` §9).

---

## 6. Como rodar

Dois processos, em dois terminais.

### Terminal 1 — API dos agentes

Na raiz do projeto (`challenge-2/`):

```bash
# Bash / Git Bash
./.venv/Scripts/python.exe -m uvicorn api:app --reload --port 8000
```

```powershell
# PowerShell
.\.venv\Scripts\python.exe -m uvicorn api:app --reload --port 8000
```

Confirme com `curl http://localhost:8000/saude` → `{"status":"ok"}`.

Por padrão o terminal mostra só metadados — se identificou compromisso e quais campos faltam. O conteúdo da conversa **não vai para o log**: são dados de saúde e dados pessoais (`CLAUDE.md` §8). Para ver tudo durante o desenvolvimento:

```bash
DEBUG_AGENTES=1 ./.venv/Scripts/python.exe -m uvicorn api:app --reload --port 8000
```

### Terminal 2 — Bot do WhatsApp

```bash
cd whatsapp-bot
node bot.js
```

Na primeira vez aparece um QR code no terminal — leia com o WhatsApp do celular. A sessão fica salva em `whatsapp-bot/auth/`.

### Demo sem WhatsApp

Roda três mensagens de teste direto no terminal, sem precisar do bot nem da API:

```bash
./.venv/Scripts/python.exe two_agents.py
```

### Barras invertidas

PowerShell usa `\`, Bash usa `/`. No Bash a barra invertida é caractere de escape — `.\.venv\Scripts\python.exe` vira `..venvScriptspython.exe` e o comando falha.

---

## 7. Quando o bot parece não reagir

O bot **ignora mensagem comum de propósito** (`bot.js:130`):

```js
// Aciona os agentes apenas com o comando, para nao chamar
// a API a cada mensagem do grupo
if (!conteudo.startsWith(COMANDO)) continue;
```

Três condições para o bot processar uma mensagem:

| Condição                      | Onde         | Falha silenciosa?                                |
| ----------------------------- | ------------ | ------------------------------------------------ |
| Começar com `!agenda`         | `bot.js:130` | Não — o log da linha 109 ainda aparece           |
| Ser de um **grupo** (`@g.us`) | `bot.js:102` | **Sim** — conversa direta não loga nada          |
| Não ser do próprio número     | `bot.js:97`  | **Sim** — mensagem sua é descartada antes do log |

As duas últimas descartam a mensagem **antes** do `console.log`. Se não aparece absolutamente nada no terminal, a causa provável é uma delas — não o comando.

Para testar sozinho, mandando do seu próprio número:

```bash
RESPONDER_PROPRIAS=1 node bot.js
```

Teste mais curto, só para ver se o bot escuta o grupo: mande `!ping` → responde "Bot funcionando!".

---

## 8. O que ainda não existe

Nada aqui está decidido contra — é escopo não implementado.

- **Gravação na agenda.** Nenhuma API de calendário conectada. O "Agente 2" do `CLAUDE.md` §5 prevê criar eventos; hoje ele só coordena a conversa. O provedor (Google Calendar, Outlook) continua em aberto — `CLAUDE.md` §10.
- **Memória entre mensagens.** Cada `!agenda` é independente. Se alguém responder "eu levo ela" na mensagem seguinte, o sistema não liga uma coisa na outra. O `CLAUDE.md` §3 passo 3 pede exatamente isso.
- **Detecção de duplicidade, atualização e cancelamento.** `CLAUDE.md` §7 itens 7.
- **Rede neural.** O requisito `CLAUDE.md` §9 pede uma. Hoje a classificação "é compromisso ou não" é feita pela LLM, no campo `e_compromisso` — não por um modelo treinado pela equipe.
- **Autorização.** Não há checagem de quem pode acionar o comando, nem de permissão de acesso à agenda de alguém. `CLAUDE.md` §6 e §11.7.
- **Base de conhecimento e MLOps.** Requisitos `CLAUDE.md` §9, ainda não iniciados.

---

## 9. Dependências externas

- **LLM:** `groq/openai/gpt-oss-20b`, via Groq. Chave em `.env` (`GROQ_API_KEY`), carregada por `load_dotenv()`.
- **`max_tokens=2000`** (`agentes.py:34`) não é folga: o `gpt-oss-20b` é modelo de raciocínio e gasta parte dos tokens no raciocínio interno. Com limite curto não sobra nada para a resposta e o CrewAI recebe texto vazio.
- **CrewAI 1.15.28**, **Baileys 7.0.0-rc14** (WhatsApp), **FastAPI/uvicorn**.
- O parse do JSON fica em `compromisso.py`, não no `instructor` do CrewAI: a versão do `instructor` deste ambiente é incompatível com o `mcp~=1.28.1` que o CrewAI exige.

---

## 10. Documentação do CrewAI

Versão em uso: **crewai 1.15.28**. Os links abaixo apontam para a doc corrente. Para fixar uma versão, troque o número na URL: `docs.crewai.com/v1.15.28/en/...`.

### Estrutura e sintaxe

| Página                                                                              | O que cobre                                                                                                 |
| ----------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| [Crews](https://docs.crewai.com/en/concepts/crews)                                  | `@CrewBase`, `@agent`, `@task`, `@crew` e o layout `config/agents.yaml` + `config/tasks.yaml`               |
| [Using annotations](https://docs.crewai.com/v1.15.24/en/learn/using-annotations.md) | exemplo completo da classe decorada                                                                         |
| [Agents](https://docs.crewai.com/en/concepts/agents)                                | `role`, `goal`, `backstory`, `max_iter`, `allow_delegation`                                                 |
| [Tasks](https://docs.crewai.com/en/concepts/tasks)                                  | `description`, `expected_output`, `context` e **`guardrail`** — guardrail não tem página própria, mora aqui |

### Processos

| Página                                                                | O que cobre                                              |
| --------------------------------------------------------------------- | -------------------------------------------------------- |
| [Processes](https://docs.crewai.com/en/concepts/processes)            | sequencial vs hierárquico                                |
| [Sequential](https://docs.crewai.com/en/learn/sequential-process)     | o processo usado hoje em `montar_crew()`                 |
| [Hierarchical](https://docs.crewai.com/en/learn/hierarchical-process) | manager delegando; vira opção real a partir de 3 agentes |

### Ferramentas — quando o coordenador ganhar o calendário

| Página                                                                           | O que cobre                                             |
| -------------------------------------------------------------------------------- | ------------------------------------------------------- |
| [Tools](https://docs.crewai.com/en/concepts/tools)                               | conceito de ferramenta                                  |
| [Criar ferramenta própria](https://docs.crewai.com/en/learn/create-custom-tools) | caminho para a API de agenda prevista no `CLAUDE.md` §5 |

### Referência

| Página                                              | O que cobre                                    |
| --------------------------------------------------- | ---------------------------------------------- |
| [CLI](https://docs.crewai.com/en/concepts/cli)      | `crewai create crew`, que gera o scaffold YAML |
| [LLMs](https://docs.crewai.com/en/concepts/llms)    | configuração do provedor — aqui, Groq          |
| [Índice completo](https://docs.crewai.com/llms.txt) | todas as páginas em texto puro                 |

### Por onde começar

[Crews](https://docs.crewai.com/en/concepts/crews) e [Tasks](https://docs.crewai.com/en/concepts/tasks). A primeira mostra o formato YAML; a segunda cobre `context` e `guardrail` — as duas peças que fazem os agentes colaborarem sem inventar dado.

### Decisão em aberto

Hoje agentes e tarefas estão em Python, em `agentes.py`, e não em YAML. As duas formas são equivalentes para o framework: o YAML é convenção da CLI, não exigência. Migrar passa a valer se entrar um terceiro agente, se a equipe for iterar prompts em conjunto, ou se a estrutura padrão do CrewAI for critério de avaliação. Decisão pendente —
