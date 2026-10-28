# Arquitetura dos agentes

Como a mensagem do grupo vira uma resposta, quem faz o quê e o que ainda não existe.

Contexto do produto: [`CLAUDE.md`](CLAUDE.md). Este documento descreve **o que está implementado hoje**, não a visão completa.

---

## 1. Visão geral

**Um agente, duas tarefas.** A configuração vive em arquivo; o Python fica com a lógica.

| Arquivo | Papel | É um processo? |
| --- | --- | --- |
| `whatsapp-bot/bot.js` | Escuta o WhatsApp, reconhece o comando, devolve a resposta ao grupo | Sim — `node bot.js` |
| `api.py` | Expõe `POST /agente`, faz a ponte entre o bot e o agente | Sim — `uvicorn api:app` |
| `crew_extrair.jsonc` | Tarefa 1: prompt e guardrail da extração | Não — configuração |
| `crew_responder.jsonc` | Tarefa 2: prompt e guardrail da resposta | Não — configuração |
| `agents/assistente_de_compromissos.jsonc` | A persona do agente e qual LLM ele usa | Não — configuração |
| `agentes.py` | A LLM, o carregamento das crews, a fusão e `processar()` | Não — módulo |
| `compromisso.py` | Modelo de dados, guardrails e a regra de fusão | Não — módulo |
| `memoria.py` | O compromisso pendente de cada grupo | Não — módulo |

`verificar.py` é o teste de fiação e não participa do fluxo do WhatsApp.

**Por que só um agente.** O "Coordenador de Cuidados" que existia antes não fazia o que o `CLAUDE.md` §5 descreve — ele só escrevia texto. O segundo agente nasce quando houver integração com agenda de verdade, e aí será o coordenador que identifica o responsável, confere autorização e cria o evento no calendário.

### O caminho de uma mensagem

```text
Você digita no grupo:  !agenda a vo Helena tem consulta no cardiologista quinta as 15h
        │
        ▼
bot.js          ← processo Node. Escuta o WhatsApp.
        │          Corta o "!agenda", pega a data de hoje, manda POST
        ▼
api.py          ← processo uvicorn na porta 8000. POST /agente
        │          Chama processar(mensagem, data, grupo_id)
        ▼
agentes.py      ← orquestra as duas tarefas, com a fusão no meio
        │
        │   memoria.py ──► compromisso pendente deste grupo
        │                         │
        ├─ TAREFA 1 "extrair" ────┤  (o pendente entra no prompt só para
        │        │                │   a LLM resolver "ela", "nesse dia")
        │        ▼                ▼
        │   JSON do que ESTA  +  pendente
        │   mensagem informa      │
        │        └────────►  FUNDIR (Python)
        │                         │
        └─ TAREFA 2 "responder" ◄─┘  recebe o compromisso completo
        │                             e pergunta só o que falta
        ▼
api.py devolve {resposta, compromisso, faltantes}
        │
        ▼
bot.js envia o texto da "resposta" no grupo
```

O agente **não fica rodando**. Nasce, trabalha e morre a cada comando — `montar_crew()` chama `load_crew()` dentro de `processar()`, e isso constrói tudo do zero. É proposital: agentes e tarefas do CrewAI guardam o resultado da última execução, então reaproveitar os mesmos objetos misturaria o contexto de conversas diferentes. `verificar.py` confirma esse isolamento a cada execução.

**O que sobrevive entre mensagens é o dado, não o agente** — o compromisso pendente guardado em `memoria.py`. Ver §4.

**Por que as tarefas estão em arquivos separados.** A fusão precisa acontecer entre as duas, e a tarefa `responder` decide o que perguntar olhando os campos nulos. Recebendo direto o extraído de "eu levo ela" — quase tudo nulo — ela perguntaria data e horário que o sistema já tinha. Com as duas no mesmo arquivo, o CrewAI as emendaria e não haveria onde entrar.

O número de chamadas de LLM continua **2**; só a orquestração saiu do CrewAI e foi para o Python.

---

## 2. Tarefa 1 — `extrair`

Definida em `crew_extrair.jsonc`.

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

Repare no `responsavel: null`. A mensagem citou a consulta, mas ninguém se ofereceu pra levar. A regra (4) do prompt diz: _mencionar uma pessoa não é o mesmo que ela ter aceitado_. Campo vazio é corrigível; campo inventado manda a família pro lugar errado.

O campo `e_compromisso` fica `false` quando a mensagem é conversa cotidiana — "alguém viu o jogo ontem?". Aí todos os outros campos ficam nulos.

### Guardrail `validar_extracao`

Em `compromisso.py:111`. Roda **depois** da LLM e **não é IA** — é código determinístico:

1. Tenta ler o JSON com `json_repair`, que tolera as falhas comuns de LLM: cerca de markdown, vírgula sobrando, aspas trocadas.
2. Valida contra o modelo Pydantic `Compromisso` (`compromisso.py:39`).
3. Checa formato e coerência: data `AAAA-MM-DD`, horário `HH:MM`, **e rejeita data no passado**.
4. Falhou? Devolve `(False, "mensagem de erro")` e o CrewAI **reexecuta a tarefa** com esse erro no prompt — até 2 vezes (`guardrail_max_retries: 2`).
5. Passou? Devolve o JSON normalizado. É exatamente esse texto que a tarefa 2 recebe.

O guardrail garante que a data seja real e não esteja no passado. Ele **não** garante que esteja certa — ver §9.

O guardrail é declarado no `crew_extrair.jsonc` como `{"python": "compromisso.validar_extracao"}`. Uma string simples ali viraria um `LLMGuardrail` — outra LLM julgando a saída — em silêncio. `verificar.py` checa que isso não aconteceu.

---

## 3. Tarefa 2 — `responder`

Definida em `crew_responder.jsonc`.

- **Entrada:** o JSON da tarefa 1, via `"context": ["extrair"]`
- **Trabalho:** resumir o que foi entendido e perguntar o que falta
- **Saída:** um texto curto, até 4 frases, em português

Ela **não vê a mensagem original** — o prompt não interpola `{mensagem}`, só recebe o `context`. Isso é de propósito: assim o agente não pode "reinterpretar" e reintroduzir um detalhe que a extração descartou.

```text
Foi identificada uma consulta de cardiologia para Dona Helena
em 29/10 as 15:00, na clinica do centro.
Quem podera acompanha-la nesse dia?
```

Duas obrigações:

- **Pedir o que falta.** Se `data` ou `horario` estão nulos, pergunta. Se não há `responsavel`, pergunta quem pode acompanhar — e **nunca escolhe alguém**.
- **Não mentir sobre agendamento.** Nada foi gravado em agenda nesta etapa.

### Guardrail `validar_resposta`

Em `compromisso.py:155`, declarado no `crew_responder.jsonc` como `{"python": "compromisso.validar_resposta"}`. Passa um regex procurando afirmações de agendamento — "agendou", "marcou", "registrou", "anotou", "colocou na agenda" e as formas em primeira pessoa. Achou? Rejeita e manda reescrever.

O regex cobre a **terceira pessoa** porque a regra (1) do prompt obriga escrever assim: um regex só com "registrei" nunca dispararia na prática.

Existe porque **nada é gravado em agenda nenhuma ainda**. Sem esse guardrail, a LLM diria "pronto, agendei!" — e a família confiaria num evento que não existe. Ver `CLAUDE.md` §4: _nunca informar que agendou se a API de calendário não confirmar a criação_.

---

## 4. A memória — `memoria.py` e a fusão

O sistema era **sem estado**: cada `!agenda` nascia do zero. Isso quebrava o caso central do `CLAUDE.md` §3 — "eu levo ela" não tinha a que se referir, e a resposta era "nenhum compromisso identificado".

Na classificação clássica, guardar esse estado move o sistema de **agente de reflexo simples** para **agente de reflexo baseado em modelo**: a entrada da regra deixa de ser só a percepção (a mensagem) e passa a ser percepção + estado. O "modelo" aqui é o compromisso pendente de cada grupo.

### O que é fundir

Juntar o que o sistema já sabia com o que a mensagem nova trouxe.

```text
GUARDADO (msg anterior)       "eu levo ela" traz      RESULTADO
  tipo:        consulta         (vazio)         →      consulta
  pessoa:      vo Helena        (vazio)         →      vo Helena
  data:        29/10            (vazio)         →      29/10
  horario:     15:00            (vazio)         →      15:00
  responsavel: (vazio)          alguem          →      (pede o nome)
```

"Eu levo ela" traz **uma** informação; o resto vem em branco. Trocar pelo novo perderia data e horário. Ignorar o novo nunca registraria a oferta.

A regra inteira cabe numa frase: **campo vazio na mensagem nova não apaga o que já estava lá.** Funciona nos dois sentidos — "na verdade é às 16h" traz valor, então substitui.

### Por que a fusão é Python, não prompt

Se a LLM fundisse, o pior caso seria **apagar em silêncio um campo confirmado** — devolver `horario: null` porque "resumiu". Nenhum guardrail pega isso: `null` é valor perfeitamente legal. O sistema então perguntaria o horário de novo, que é justamente o bug sendo consertado — só que intermitente e não reproduzível.

Em Python, "valor nulo não apaga" é código. Estruturalmente impossível.

Mesmo princípio do resto do projeto: `agentes.py` pede, `compromisso.py` garante.

### Onde cada peça mora

| Função | Arquivo | Responde |
| --- | --- | --- |
| `fundir()` | `compromisso.py` | **como** dois registros se combinam |
| `deve_fundir()` | `compromisso.py` | se a fusão se aplica |
| `carregar_pendente()` / `salvar_pendente()` | `memoria.py` | **onde** o estado fica |

`fundir` é regra sobre o dado, não sobre o armazenamento — por isso fica em `compromisso.py`, junto do resto que é testável sem LLM. Trocar o dicionário por SQLite não muda uma vírgula dela.

### Decidir se a mensagem se refere ao pendente

A LLM devolve um campo `refere_se_ao_pendente`. **Ele é tratado como palpite, não como decisão** — e isso não é zelo preventivo, é resposta a uma falha medida.

Rodando "eu, Maysa irei levar a minha vo" cinco vezes contra o mesmo pendente, a LLM devolveu `false` em uma delas. Quando isso acontece, a mensagem vira um compromisso **novo e vazio**: data, horário e local somem, e o grupo é perguntado de novo sobre tudo. Aconteceu num teste real no WhatsApp.

Por isso `deve_fundir` (`compromisso.py`) confere antes de acreditar. Mesmo com o campo `false`, duas regras ainda fundem:

- **A mensagem não traz nenhum campo de identidade** (`tipo`, `pessoa_idosa`, `data`). Sem nenhum deles ela não descreve compromisso próprio — só pode estar completando o que existia. É o caso de "eu levo ela".
- **Os campos de identidade que ela traz batem com o pendente.** Mesmo compromisso, dito de novo.

Só vira compromisso novo quando há **conflito real** — exame no dia 5 quando o pendente é consulta no dia 28, ou outra pessoa idosa.

Resultado: a LLM continua opinando, mas não decide sozinha. Mesmo princípio dos guardrails — prompt pede, código garante.

### A outra invariante: oferta resolvida

`coerir()` aplica uma regra depois da fusão: **com `responsavel` preenchido, `alguem_se_ofereceu` vira `false`.**

Sem isso, os dois campos ficavam ligados ao mesmo tempo depois de "eu, Maysa irei levar" — e a resposta dizia que alguém se ofereceu *e* que a tarefa já tinha dono, sobre a mesma pessoa. Quem se ofereceu e foi identificado deixa de ser "alguém".

### Quem acompanha não é preenchido sozinho

`CLAUDE.md` §6: o sistema **não decide sozinho quem leva a pessoa idosa**. "Eu levo ela" não identifica ninguém — atribuir a tarefa a partir de um apelido do WhatsApp seria exatamente isso.

Então `responsavel` fica nulo e o campo `alguem_se_ofereceu` vira `true`. A resposta reconhece a oferta e pede o nome. Consequência boa: o bot não precisa enviar o nome de ninguém, só o ID do grupo.

### Quando o pendente é descartado

| Situação | Onde |
| --- | --- |
| Compromisso completo **e** com responsável | `agentes._guardar` |
| Data já passou | `memoria._vencido`, na leitura |
| Parado há mais de 48h | `memoria._vencido`, na leitura |
| Data corrompida no armazenamento | `memoria._vencido` |
| Chegou um compromisso diferente | substitui |
| Conversa cotidiana | não mexe em nada |

O descarte por tempo mora na **leitura**, não na escrita: a passagem do tempo é o único evento que ninguém dispara — um pendente válido ontem venceu hoje sozinho.

"Completo" exige `responsavel`, não só os campos obrigatórios. `OBRIGATORIOS` é o mínimo para *agendar*; o caso do `CLAUDE.md` §3 só termina quando alguém assume.

### Armazenamento e privacidade

Dicionário em memória nesta etapa, para provar a lógica. SQLite é o próximo passo, e por isso o acesso está isolado em duas funções.

A chave guardada é o **hash** do ID do grupo, não o JID. O armazenamento contém dados de saúde e vai para disco quando virar SQLite — não precisa levar junto o identificador da conversa (`CLAUDE.md` §8).

### Concorrência

Um `threading.Lock` por grupo, segurado durante o `processar()` inteiro. O risco não é corromper o dicionário — `dict` do CPython é atômico. É a janela de alguns segundos entre carregar e salvar, que atravessa duas chamadas de LLM: dois pedidos do mesmo grupo em paralelo leriam o mesmo pendente, e o segundo a salvar apagaria a fusão do primeiro.

Lock por grupo, e não global: um lock único serializaria grupos diferentes atrás de 5s de LLM, o oposto do que o threadpool do FastAPI existe para fazer.

> **Rode com um worker.** `uvicorn --workers N` com N>1 dá um dicionário por processo, e mensagens do mesmo grupo cairiam em processos diferentes. Vale até o SQLite entrar.

---

## 5. `compromisso.py` — a metade sem IA

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
2. **Um lugar só.** As duas tarefas e os scripts de terminal usam as mesmas regras. Duplicar daria divergência.
3. **Sobrevive à troca de framework.** O arquivo não importa nada do CrewAI. Se o framework de agentes mudar, a parte que impede o sistema de inventar dado atravessa a migração intacta.

---

## 6. Por que duas tarefas e não uma

Trabalhos diferentes, falhas diferentes.

| Tarefa | Como ela erra | O que pega o erro |
| --- | --- | --- |
| 1 — `extrair` | Extrai dado errado, inventa data | `validar_extracao`: Pydantic + formato + data no passado |
| 2 — `responder` | Fala demais, promete o que não fez | `validar_resposta`: regex de afirmação de agendamento |

Uma tarefa única misturaria as duas responsabilidades num prompt só, e qualquer validação teria que adivinhar qual metade falhou. Separando, cada guardrail sabe exatamente o que está checando e o retry reexecuta só a etapa quebrada.

Há um segundo ganho, menos óbvio: a tarefa 2 recebe apenas o JSON validado. Fundir as duas devolveria a mensagem original ao contexto da redação, e com ela a chance de reintroduzir um detalhe que a extração descartou por não estar escrito.

Custo: duas chamadas de LLM em vez de uma.

**Nota sobre o requisito acadêmico.** O `CLAUDE.md` §9 pede *pelo menos dois agentes de IA colaborando*. Duas tarefas do mesmo agente **não** cumprem isso. O requisito fica em aberto até o coordenador de agenda existir — ver §9.

### Orquestração: Python hoje, Flows depois

Duas crews em arquivos separados, com código entre elas, é padrão — sistemas reais raramente são uma crew só. Tutorial quase sempre mostra uma porque tutorial não tem lógica determinística no meio.

Hoje a orquestração está em `agentes.py`, em funções comuns: chama a crew 1, funde, chama a crew 2. Linear, sem ramificação, ~20 linhas.

O CrewAI tem um mecanismo próprio para isso, **Flows**, disponível na versão instalada:

```python
from crewai.flow.flow import Flow, start, listen

class FluxoCompromisso(Flow):
    @start()
    def extrair(self): ...              # crew 1

    @listen(extrair)
    def fundir_e_responder(self, novo): ...   # Python no meio + crew 2
```

Mesma ideia — crews separadas com código entre elas — só que a orquestração fica declarada em decoradores, e o `Flow` traz estado embutido.

**Por que não agora:** para um fluxo reto de duas etapas, seria estrutura a mais. Python simples é mais fácil de ler e de explicar.

**Quando passa a valer:**

- **Ramificação** — "se é cancelamento vai por aqui, se é remarcação por ali". O `CLAUDE.md` §4 prevê os dois.
- **Mais etapas** — com o coordenador de agenda, viram três ou quatro.
- **Estado do fluxo** — parte do que `memoria.py` faz à mão.

Os três chegam juntos quando o segundo agente entrar. É o momento natural de reavaliar.

Doc: [Flows](https://docs.crewai.com/en/concepts/flows).

---

## 7. Como rodar

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

### Testar sem WhatsApp

Chame a API direto. Ela devolve o compromisso estruturado junto com a resposta — é o mesmo que o bot recebe:

```bash
curl -X POST http://localhost:8000/agente \
     -H "Content-Type: application/json" \
     -d '{"mensagem":"a vo Helena tem consulta quinta as 15h","grupo_id":"teste"}'
```

Repetindo com o mesmo `grupo_id`, a memória entra em jogo — é assim que se testa a sequência do `CLAUDE.md` §3 sem parear o WhatsApp. Sem `grupo_id`, cada chamada é independente.

### Verificação da fiação

Monta as duas crews e inspeciona os objetos, **sem gastar chamada de LLM**. Roda em um segundo:

```bash
./.venv/Scripts/python.exe verificar.py
```

Confere oito coisas que falhariam em silêncio: os guardrails ainda são as funções Python e não `LLMGuardrail`; cada carregamento devolve objetos próprios; a tarefa de resposta está sem `context`; os placeholders que o `agentes.py` preenche existem nos prompts; `{mensagem}` vem antes de `{pendente}`; nada ficou memoizado no cache global do CrewAI; e o agente usa a LLM compartilhada com `max_tokens=2000`.

Vale rodar a cada alteração nos `.jsonc` e depois de atualizar o CrewAI.

### Barras invertidas

PowerShell usa `\`, Bash usa `/`. No Bash a barra invertida é caractere de escape — `.\.venv\Scripts\python.exe` vira `..venvScriptspython.exe` e o comando falha.

---

## 8. Quando o bot parece não reagir

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

## 9. O que ainda não existe

Nada aqui está decidido contra — é escopo não implementado.

- **O segundo agente, e com ele a gravação na agenda.** Nenhuma API de calendário conectada. O "Agente 2" do `CLAUDE.md` §5 — identificar o responsável, conferir autorização, criar o evento — ainda não existe. É o próximo passo, e é o que destrava o requisito de **dois agentes colaborando** (`CLAUDE.md` §9), hoje em aberto. O provedor (Google Calendar, Outlook) continua indefinido — `CLAUDE.md` §10.
- **Resolução confiável de data relativa.** O guardrail rejeita data no passado e fora de formato, mas não sabe se a data está *certa*. Em execuções reais, "quinta-feira" às vezes vira a data correta, às vezes fica nula, às vezes vira a data de hoje. A regra (2) do prompt manda calcular a partir de `{data_mensagem}`, e o modelo nem sempre obedece. **Com a memória, a consequência cresceu:** uma data errada não estraga só uma resposta — fica guardada e contamina as mensagens seguintes até vencer. `memoria._vencido` cobre data no passado; data errada no futuro não tem rede. Opções: calcular a data em Python a partir do dia da semana extraído, ou pedir confirmação ao grupo sempre que a origem for relativa.
- **Mais de um compromisso pendente por grupo.** A memória guarda **um**. Um compromisso novo substitui o anterior, mesmo que o anterior ainda estivesse incompleto.
- **Detecção de duplicidade, atualização e cancelamento.** `fundir()` nunca apaga campo — só preenche e corrige. Não há como cancelar um compromisso pela conversa. `CLAUDE.md` §7 item 7.
- **Memória que sobrevive a reiniciar.** É um dicionário no processo: matar o uvicorn apaga tudo, e `--workers N` com N>1 daria um dicionário por processo. SQLite é o próximo passo — o acesso já está isolado em `carregar_pendente` / `salvar_pendente` para a troca mexer num arquivo só.
- **Rede neural.** O requisito `CLAUDE.md` §9 pede uma. Hoje a classificação "é compromisso ou não" é feita pela LLM, no campo `e_compromisso` — não por um modelo treinado pela equipe.
- **Autorização.** Não há checagem de quem pode acionar o comando, nem de permissão de acesso à agenda de alguém. `CLAUDE.md` §6 e §11.7.
- **Base de conhecimento e MLOps.** Requisitos `CLAUDE.md` §9, ainda não iniciados.

---

## 10. Dependências externas

- **LLM:** `groq/openai/gpt-oss-20b`, via Groq. Chave em `.env` (`GROQ_API_KEY`), carregada por `load_dotenv()`.
- **`max_tokens=2000`** não é folga: o `gpt-oss-20b` é modelo de raciocínio e gasta parte dos tokens no raciocínio interno. Com limite curto não sobra nada para a resposta e o CrewAI recebe texto vazio. Fica em `agentes.py` porque `temperature` e `max_tokens` não são expressáveis como string de modelo no JSONC — o arquivo do agente aponta para o objeto com `{"python": "agentes.LLM_COMPARTILHADA"}`.
- **CrewAI 1.15.28**, **Baileys 7.0.0-rc14** (WhatsApp), **FastAPI/uvicorn**.
- **Limite de taxa do Groq.** A conta gratuita permite 8.000 tokens por minuto no `gpt-oss-20b`. Cada mensagem gasta ~3.000 (duas tarefas, mais retry se um guardrail rejeitar), então o teto prático é **2 mensagens por minuto**. Passando disso, o LiteLLM levanta `RateLimitError`. Suficiente para um grupo familiar; apertado para rodar bateria de testes em sequência.
- O parse do JSON fica em `compromisso.py`, não no `instructor` do CrewAI: a versão do `instructor` deste ambiente é incompatível com o `mcp~=1.28.1` que o CrewAI exige.

---

## 11. Documentação do CrewAI

Versão em uso: **crewai 1.15.28**. Os links abaixo apontam para a doc corrente. Para fixar uma versão, troque o número na URL: `docs.crewai.com/v1.15.28/en/...`.

### Estrutura e sintaxe

| Página | O que cobre |
| --- | --- |
| [Crews](https://docs.crewai.com/en/concepts/crews) | o formato JSONC (`crew*.jsonc` + `agents/`), que é o usado aqui, e o YAML clássico `@CrewBase` |
| [Agents](https://docs.crewai.com/en/concepts/agents) | `role`, `goal`, `backstory`, `max_iter`, `allow_delegation` |
| [Tasks](https://docs.crewai.com/en/concepts/tasks) | `description`, `expected_output`, `context` e **`guardrail`** — guardrail não tem página própria, mora aqui |
| [Using annotations](https://docs.crewai.com/v1.15.24/en/learn/using-annotations.md) | o caminho YAML com decoradores, **não usado aqui** — ver a decisão no fim desta seção |

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
| [CLI](https://docs.crewai.com/en/concepts/cli) | `crewai create crew`, que gera o formato JSONC por padrão |
| [LLMs](https://docs.crewai.com/en/concepts/llms) | configuração do provedor — aqui, Groq |
| [Índice completo](https://docs.crewai.com/llms.txt) | todas as páginas em texto puro |

### Por onde começar

[Crews](https://docs.crewai.com/en/concepts/crews) e [Tasks](https://docs.crewai.com/en/concepts/tasks). A primeira mostra o formato dos arquivos; a segunda cobre `context` e `guardrail` — as duas peças que fazem as tarefas colaborarem sem inventar dado.

### Decisão: JSONC, não YAML

O CrewAI 1.15 tem dois formatos. **JSONC** (`crew*.jsonc` + `agents/`) é o recomendado para projetos novos e o que `crewai create crew` gera; o **YAML clássico** (`config/*.yaml` + `@CrewBase`) fica atrás da flag `--classic` e segue suportado.

Escolhemos JSONC por um motivo concreto, verificado no código do pacote instalado:

> **No YAML, um guardrail em função Python não é expressável.** `crew_base.py:766-767` faz passthrough no-op da chave `guardrail`, e `task.py:394-407` converte a string resultante num `LLMGuardrail` — outra LLM julgando a saída. Em silêncio, sem erro.

Os guardrails deste projeto são a garantia de que o sistema não inventa data nem mente sobre agendamento. Trocá-los por um juiz probabilístico sem aviso é o pior modo de falha possível aqui. No JSONC, `{"python": "compromisso.validar_extracao"}` resolve a função de verdade (`json_loader.py:1506-1536`) ou levanta `JSONProjectError`.

Dois efeitos colaterais bons:

- **`agent`, `context` e `llm` também cabem no arquivo.** No desenho YAML, metade da configuração teria que ficar em Python de qualquer jeito.
- **`load_crew()` não memoiza.** Os decoradores `@agent`/`@task`/`@crew` guardam resultado num cache global de módulo chaveado por `id(self)` (`project/utils.py:15, 33-34`), sem TTL nem limpeza pública. Numa API concorrente isso significa vazamento de memória com o compromisso dentro, e risco de servir o agente do pedido anterior. O loader JSONC não tem esse problema — e `verificar.py` confirma a cada execução.
