# Arquitetura dos agentes

Como a mensagem do grupo vira uma resposta, quem faz o quê e o que ainda não existe.

Contexto do produto: [`CLAUDE.md`](../CLAUDE.md). Este documento descreve **o que está implementado hoje**, não a visão completa.

---

## 1. Visão geral

```text
challenge-2/
├── app/
│   ├── main.py              # sobe o FastAPI e inclui o router
│   ├── compromisso.py       # modelo de dados e guardrails — sem IA
│   ├── routes/agente.py     # POST /agente e GET /saude
│   ├── agents/
│   │   ├── interprete.py    # agente 1 — quem ele é
│   │   ├── coordenador.py   # agente 2 — quem ele é
│   │   └── RAG.py           # agente 3 — quem ele é, mais a tool e o índice
│   ├── tools/
│   │   ├── agenda.py        # a tool do agente 2 — grava os compromissos
│   │   └── banco.py         # SQLite ou Postgres, pela DATABASE_URL
│   └── graph/
│       ├── estado.py        # o estado que atravessa o grafo
│       ├── prompts.py       # o que se pede a cada agente
│       ├── nos.py           # os nós e as arestas condicionais
│       └── grafo.py         # monta o grafo e expõe processar()
├── arquivos/                # o PDF do Guia do Cuidador
├── docs/                    # este arquivo
├── whatsapp-bot/bot.js      # o bot
├── CLAUDE.md
└── README.md
```

| Arquivo                  | Papel                                                               | É um processo?                    |
| ------------------------ | ------------------------------------------------------------------- | --------------------------------- |
| `whatsapp-bot/bot.js`    | Escuta o WhatsApp, reconhece o comando, devolve a resposta ao grupo | Sim — `node bot.js`               |
| `app/main.py`            | Sobe a API e registra as rotas                                      | Sim — `uvicorn app.main:app`      |
| `app/routes/agente.py`   | Expõe `POST /agente`, faz a ponte entre o bot e os agentes          | Não — módulo                      |
| `app/graph/grafo.py`     | Monta o grafo e expõe `processar()`                                 | Não — módulo                      |
| `app/graph/nos.py`       | A LLM, os nós e as funções de roteamento                            | Não — módulo                      |
| `app/graph/prompts.py`   | O que se pede a cada agente e as respostas fixas                    | Não — módulo                      |
| `app/graph/estado.py`    | O `EstadoGrupo` e o limite de tentativas                            | Não — módulo                      |
| `app/agents/*.py`        | Define cada agente: papel, objetivo e história                      | Não — módulos                     |
| `app/compromisso.py`     | Modelo de dados e guardrails determinísticos                        | Não — módulo                      |

Os agentes ficam separados do que se pede a eles de propósito: **quem é o agente** muda pouco, **o que se pede a ele** muda a cada ajuste de regra. Em arquivos diferentes, mexer numa regra não arrisca o outro. Por isso a persona mora em `app/agents/` e o prompt da tarefa em `app/graph/prompts.py`.

### O caminho de uma mensagem

```text
Você digita no grupo:  !agenda a vo Helena tem consulta no cardiologista quinta as 15h
        │
        ▼
bot.js              ← processo Node. Escuta o WhatsApp.
        │              Corta o "!agenda", pega a data de hoje, manda POST
        ▼
routes/agente.py    ← processo uvicorn na porta 8000. POST /agente
        │              Chama processar(mensagem, data)
        ▼
graph/grafo.py      ← invoca o grafo com um estado novo
        │
        ▼
```

```text
        __start__
            │
            ▼
      ┌─ interpretar ◄──────────────┐  AGENTE 1 — chama a LLM
      │     │                       │
      │     ▼                       │ erro, se ainda há tentativa
      │  validar_extracao ──────────┘  guardrail — sem LLM
      │     │
      │     ├─ 3 tentativas sem JSON válido ─► falha_extracao ─► __end__
      │     │
      │     ├─ classificacao ≠ cuidado ──────► resposta_fixa ──► __end__
      │     │                                  (sem LLM)
      │     ▼ classificacao = cuidado
      │  fundir                        junta com o combinado — sem LLM
      │     │
      │     ├─ contradiz o combinado ──────► perguntar_conflito ─► __end__
      │     │                                 (sem LLM)
      │     ▼
      │  coordenar ◄──────────────────┐  AGENTE 2 — chama a LLM
      │     │                         │
      │     ▼                         │ erro, se ainda há tentativa
      │  validar_resposta ────────────┘  guardrail — sem LLM
      │     │
      │     ├─ 3 tentativas reprovadas ─────► falha_coordenacao ─┐
      │     │                                                    │
      └─────▼ encerrar ───────────────────────────────────────►  │
                                                                 ▼
                                              todos os caminhos: limpar ─► __end__
```

Os cinco caminhos terminais passam por `limpar` antes do fim. É ele que tira o texto cru da conversa do estado, antes de o checkpointer gravar.

```text
routes/agente.py devolve {resposta, compromisso, faltantes}
        │
        ▼
bot.js envia o texto da "resposta" no grupo
```

### O Roteador: a entrada é o comando

O grafo tem quatro portas de entrada, escolhidas por `rumo_inicial()` (`app/graph/nos.py`) a partir do comando que a pessoa usou no grupo:

| Comando | Entra em | Chama LLM? |
| --- | --- | --- |
| `!agenda <texto>` | `interpretar` — agentes 1 e 2 | sim |
| `!compromisso` | `responder_compromisso` | **não** |
| `!andamento <pergunta>` | `responder_andamento` | sim, uma vez |
| `!duvida <pergunta>` | `responder_duvida` — agente 3 | sim, duas ou mais |

Este é o **Roteador** do desenho original no LangGraph Builder, mas determinístico: quem escolhe o comando já declarou a intenção, então não há o que uma LLM precise classificar na entrada. Mais barato e sem chance de errar.

`!ajuda` e `!ping` nem chegam à API — o `bot.js` responde sozinho. A ajuda é justamente o que a pessoa procura quando algo não está funcionando, e não faz sentido depender da API no ar para obtê-la. Qualquer `!` desconhecido também cai na ajuda, em vez de ser ignorado em silêncio.

### `!compromisso` — sem LLM nenhuma

Duas seções, as duas sem token nenhum:

- **o que o grupo está montando** — `resumir()` (`app/compromisso.py`) formata o estado do grafo. Campo vazio vira "ainda nao informado", explicitamente;
- **o que já foi gravado** — `listar_ativos()` lê a tabela e `resumir_gravados()` formata.

A segunda existe porque o estado do grafo some: quando o compromisso encerra, o thread é apagado (`grafo.py`). O que está no banco fica.

### `!andamento` — pergunta livre, com guardrail próprio

O agente recebe o compromisso acumulado e as últimas falas, e responde só a partir deles. Sem compromisso em aberto, responde um texto fixo sem acionar LLM: não havendo dado, qualquer resposta gerada seria invenção.

O guardrail é o `validar_andamento()` (`app/compromisso.py`), que soma ao `validar_resposta` uma checagem própria da pergunta livre:

| Situação | Resultado |
| --- | --- |
| compromisso **sem data** e a resposta cita mês ou dd/mm | reprova, manda dizer que não foi informada |
| compromisso **sem horário** e a resposta cita `15h` ou `15:00` | reprova, idem |

Sem isso, "quando é a consulta?" com data nula é um convite ao chute — e um evento com data inventada é o não-sucesso explícito do `CLAUDE.md` §7.

### `!duvida` — o Agente 3 e o Guia do Cuidador

`!andamento` pergunta sobre o que o grupo combinou. `!duvida` pergunta sobre cuidado — "como prevenir quedas em casa?" — e quem responde é o Agente 3, a partir do **Guia do Cuidador** (`arquivos/`, 250 páginas). É a base de conhecimento do `CLAUDE.md` §9.

Ele é o único agente com ferramenta. O `RAG.py` divide o PDF em trechos de 1000 caracteres, indexa cada um com o modelo `intfloat/multilingual-e5-base` e expõe a busca como a tool `pega_contexto`. **Quem decide chamar a tool é a LLM**, não o grafo:

```text
pergunta → LLM decide buscar → tool devolve 4 trechos com [Pagina N]
         → LLM responde citando a página → guardrail confere
```

O índice fica em memória e é montado quando a API sobe (`app/main.py`), não na primeira pergunta: o modelo tem ~1 GB e indexar o PDF leva minutos. Falhar aí não derruba a API — só o `!duvida` para.

O compromisso do grupo **não** entra neste prompt. A pergunta é sobre cuidado, não sobre o combinado, e assim nenhum dado de saúde da pessoa idosa vai para esta conversa (`CLAUDE.md` §8).

#### Guardrail `validar_orientacao`

Os outros guardrails pegam dado de compromisso inventado. Este pega saúde inventada:

| Situação | Resultado |
| --- | --- |
| resposta vazia ou com menos de 15 caracteres | reprova |
| cita dose — `500mg`, `2 comprimidos`, `10 gotas` | reprova |
| manda dar, tomar ou alterar medicamento | reprova |
| não cita página **e** não diz "não sei" | reprova |

A última linha é a principal. O agente decide se consulta o Guia — isso é julgamento da LLM. A aprovação não é: ou a resposta mostra de onde saiu, ou admite que não sabe. Terceira opção é invenção, e é o `CLAUDE.md` §5 na prática.

`tome banho sentada` — que está no Guia — passa: a regra de prescrição exige objeto de medicamento.

---

O roteamento de classificação, por sua vez, acontece **depois** da extração, não antes. É o Agente 1 que produz o campo `classificacao`, e sem ele não há como saber se vale chamar o Agente 2. Um roteador antes dos agentes teria que reclassificar a mensagem por conta própria — uma terceira chamada de LLM decidindo o mesmo que o Agente 1 já decide.

O grafo compilado (`app/graph/grafo.py:113`) é montado **uma vez só**, na importação, e reaproveitado entre pedidos. Isso é seguro porque ele não guarda estado: o estado mora no checkpointer, separado por `thread_id`. A versão anterior, em CrewAI, precisava remontar a Crew a cada chamada — agentes e tarefas guardavam o resultado da última execução, e reaproveitá-los misturaria o contexto de conversas diferentes.

---

## 1a. Memória entre mensagens

O grupo não combina um compromisso numa mensagem só. Combina em três:

```text
"a vó helena tem uma consulta amanhã"           → tipo, pessoa, data
"é uma consulta com cardiologista, às 15h"      → especialidade, horário
"a maysa a acompanhará"                         → responsável
```

Cada extração está correta **para a sua mensagem**. O que junta as três é o checkpointer do LangGraph (`app/graph/grafo.py:109`) mais o nó `fundir` (`app/graph/nos.py:141`).

### `thread_id`: o JID do grupo

O `bot.js` manda o JID do grupo junto com a mensagem; a rota repassa; o `processar()` usa como `thread_id`. É isso que separa a conversa de uma família da de outra — sem ele, todos os grupos dividiriam um thread só e o compromisso de uma família apareceria na resposta de outra.

O estado fica em `dados/conversas.sqlite`, **fora do repositório** (`.gitignore`): contém dado de saúde (`CLAUDE.md` §8).

### `fundir`: acumular sem sobrescrever

Código determinístico, sem LLM. A regra é conservadora:

- Campo que a mensagem nova informa, entra.
- Campo que ela deixa nulo, **preserva o valor anterior**. Quem não mencionou o horário não está cancelando o horário.
- Campo que ela **contradiz**, não funde: marca conflito.

A contradição é tratada em `perguntar_conflito` (`app/graph/nos.py:181`), que responde ao grupo sem alterar nada:

```text
Esta informacao nao bate com o que ja estava combinado
(data: antes 2026-11-20, agora 2026-11-25). Isso e uma remarcacao do
mesmo compromisso ou um compromisso diferente? Nada foi alterado ate
alguem confirmar.
```

Fundir no escuro misturaria duas consultas numa só — exatamente a duplicidade que o `CLAUDE.md` §4 manda evitar. Perguntar é a resposta honesta enquanto o sistema não souber distinguir remarcação de compromisso novo.

Quais campos contam como contradição está em `CAMPOS_EXCLUDENTES` (`app/graph/estado.py:29`). `responsavel` fica de fora de propósito: trocar quem acompanha é combinação normal do grupo, não sinal de que mudou o compromisso.

### `encerrar`: quando o thread recomeça

Em `app/graph/nos.py:198`. O compromisso fecha quando não falta nenhum campo obrigatório **e** há responsável. A partir daí, a próxima mensagem do grupo começa um compromisso novo em vez de somar neste.

O responsável entra na conta embora não seja obrigatório: o assistente acabou de perguntar quem acompanha, e encerrar antes da resposta chegar faria o "eu levo ela" seguinte cair num compromisso novo e vazio.

**Fechado não significa agendado.** Nada foi gravado em agenda nenhuma.

### Quem é "eu"

O `bot.js` manda também o `pushName` de quem escreveu. Sem ele, "eu levo ela" não preenche responsável nenhum — e está certo assim: "eu" não identifica ninguém, e o `CLAUDE.md` §6 proíbe atribuir a tarefa a alguém sem confirmação. Com o autor, a regra (4a) do prompt resolve a primeira pessoa: quem aceitou é quem escreveu.

O nome do autor **não vai para o log**: é dado pessoal (`CLAUDE.md` §8).

### Histórico do grupo

O estado guarda as **últimas 12 falas** do grupo (`MAX_HISTORICO`, `app/graph/estado.py:49`), contando mensagens e respostas do assistente. Elas vão no prompt do Agente 1 (`HISTORICO`, `app/graph/prompts.py:118`).

As respostas do assistente entram junto de propósito: sem elas, o agente não tem como saber que uma fala curta — "sim, foi" — está respondendo a uma pergunta dele.

O limite existe por dois motivos. O prompt cresce a cada fala guardada, e no free tier do Groq (8000 TPM) isso vira erro 429 rápido. E conversa gravada é conteúdo bruto, que o `CLAUDE.md` §8 manda evitar — guardar as últimas falas resolve a referência sem virar arquivo da vida do grupo.

O histórico **informa, não decide**. A fonte de verdade continua sendo o `compromisso` estruturado, validado pelos guardrails. O prompt diz ao agente para usar as falas só para entender a quem a mensagem se refere, não para reextrair dado antigo.

### Remarcação: fechando o ciclo do conflito

A pergunta de conflito era um beco sem saída — o assistente perguntava "é remarcação ou compromisso diferente?" e ninguém conseguia responder. Agora responde, por duas vias:

| Via | Quando | Onde |
| --- | --- | --- |
| Campo `remarcacao` na extração | a própria mensagem diz que mudou: "na verdade é dia 25" | `app/compromisso.py`, modelo `Compromisso` |
| `confirma_remarcacao()` | a mensagem confirma a pergunta do assistente: "sim, foi remarcado" | `app/compromisso.py:59` |

A segunda via é regex, não LLM — e isso foi aprendido na prática. Tentar pelo prompt falhou duas vezes: com o bloco do histórico junto, que manda não trazer dado de fala antiga, o `gpt-oss-20b` devolvia `remarcacao: false` mesmo com a pergunta explícita no prompt. Reconhecer "sim" depois de uma pergunta é casamento de padrão curto, não julgamento.

A negativa vem primeiro no `confirma_remarcacao()`: "não, é outro exame" contém "outro" e não pode ser lido como confirmação.

Para a confirmação ter o que aplicar, a extração rejeitada fica guardada em `pendente` (`app/graph/estado.py`). Sem isso, "sim, foi remarcado" não teria efeito — a data nova já teria sido descartada no turno do conflito. Foi exatamente o bug observado no primeiro teste.

### Limpeza: o que fica gravado

O checkpointer grava um checkpoint **por passo do grafo**, não por mensagem. Medido: 5 mensagens no mesmo grupo geraram 44 checkpoints e 663 KB. E o estado inclui o campo `mensagem` — ou seja, sem limpeza o texto cru da conversa, o nome da pessoa idosa e a especialidade médica ficam em disco, junto com todas as tentativas reprovadas pelos guardrails.

Duas medidas, nos dois momentos:

| Quando | O quê | Onde |
| --- | --- | --- |
| Fim de **toda** execução | nó `limpar` guarda a troca no histórico e zera `mensagem`, `extracao_bruta` e `resposta_bruta` | `app/graph/nos.py:366` |
| Compromisso **encerrado** | `memoria.delete_thread(thread)` apaga checkpoints e writes daquele grupo | `app/graph/grafo.py`, no fim de `processar()` |

Nota de honestidade: desde que o histórico entrou, **o texto das últimas 12 falas fica gravado**. O `limpar` zera o campo `mensagem` da execução atual, mas a mesma fala já foi copiada para o histórico. O que a limpeza garante hoje é o teto — 12 falas, não a conversa inteira — e o apagamento total quando o compromisso encerra.

O `limpar` preserva `resposta` e `extracao` de propósito: o `processar()` lê os dois **depois** do `invoke`, para o retorno e para o log da rota. E preserva `compromisso` e `encerrado`, que são o que a próxima mensagem precisa.

Apagar o thread encerrado não muda comportamento nenhum: com `encerrado = True` o `fundir` já partia do zero, então aquele thread nunca mais seria lido. **Mas apaga de vez** — perguntar depois "quando foi a consulta da vó?" não tem resposta. Decisão consciente; o caminho para mudar isso está na §8.

O `delete_thread` roda em `try/except`: falha de limpeza não pode derrubar uma resposta já pronta. O log registra só o tipo do erro, nunca o conteúdo.

**Ressalva honesta:** apagar linhas no SQLite libera as páginas, mas não encolhe o arquivo — os bytes antigos continuam lá até um `VACUUM` reescrever o banco. Nenhuma consulta os devolve, mas quem abrir o arquivo com um editor binário pode encontrá-los. Para o protótipo, com dados fictícios, está bem; antes de dados reais, o `VACUUM` precisa entrar numa rotina.

```bash
./.venv/Scripts/python.exe -c "import sqlite3; sqlite3.connect('dados/conversas.sqlite', isolation_level=None).execute('vacuum')"
```

### `RETER_HISTORICO=1`

Desliga as duas medidas. Com ela, o banco guarda cada passo de cada execução e nada é apagado — serve para inspecionar o grafo rodando, que é o requisito de explicabilidade do `CLAUDE.md` §9.

```bash
RETER_HISTORICO=1 ./.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000
```

**Só em desenvolvimento, com dados fictícios.** Ligada, o texto cru das conversas volta a ficar gravado.

### Contexto para o Agente 1

Quando há compromisso em aberto, ele vai no prompt do Agente 1 (`CONTEXTO_EM_ABERTO`, `app/graph/prompts.py:100`). Sem isso o agente lê cada mensagem isolada e "a maysa a acompanhará" vira `conversa` — sozinha, a frase não fala de saúde nenhuma.

---

## 2. Agente 1 — Intérprete de Compromissos

Persona em `app/agents/interprete.py`, instruções em `PROMPT_INTERPRETAR` (`app/graph/prompts.py:17`), execução no nó `interpretar()` (`app/graph/nos.py:83`).

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
  "classificacao": "cuidado"
}
```

Repare no `responsavel: null`. A mensagem citou a consulta, mas ninguém se ofereceu pra levar. A regra (4) do prompt (`app/graph/prompts.py:28`) diz: _mencionar uma pessoa não é o mesmo que ela ter aceitado_. Campo vazio é corrigível; campo inventado manda a família pro lugar errado.

### O que conta como compromisso

O campo `classificacao` tem três valores, definidos na regra (5) do prompt:

| Valor            | Quando                                                                                                          | Exemplo                             | O que o grupo recebe              |
| ---------------- | --------------------------------------------------------------------------------------------------------------- | ----------------------------------- | --------------------------------- |
| `cuidado`        | consulta, exame, retorno, vacina, fisioterapia, terapia, cirurgia, internação, entrega ou troca de medicação     | "consulta no cardiologista quinta"  | resumo + o que falta              |
| `fora_do_escopo` | compromisso futuro que não é de cuidado da pessoa idosa                                                          | "reunião de trabalho quinta às 10h" | "isto está fora do que acompanho" |
| `conversa`       | comentário, pergunta ou relato do que já passou, sem nada combinado                                              | "o almoço de domingo estava ótimo"  | "nenhum compromisso identificado" |

Só em `cuidado` os demais campos são preenchidos; nos outros dois ficam todos nulos.

É também esse campo que decide o caminho no grafo (`rumo_apos_extracao()`, `app/graph/nos.py:210`). Em `fora_do_escopo` e `conversa` a resposta é um texto fixo de `RESPOSTA_FIXA` (`app/graph/prompts.py:105`) e o Agente 2 nem roda. Na versão em CrewAI isso custava uma chamada de LLM inteira para devolver uma frase que nunca muda.

A separação entre os dois últimos existe para o assistente não responder "nenhum compromisso identificado" a quem acabou de combinar um compromisso — seria errado e confuso — nem se oferecer para organizar agenda de trabalho, que não é o escopo do projeto (`CLAUDE.md` §1 e §11.2).

O valor padrão do campo é `conversa` (`app/compromisso.py:53`). Se a LLM omitir a chave, o sistema não age — a falha cai para o lado de não fazer nada.

### Guardrail `validar_extracao`

Em `app/compromisso.py:116`, chamado pelo nó de mesmo nome (`app/graph/nos.py:103`). Roda **depois** da LLM e **não é IA** — é código determinístico:

1. Tenta ler o JSON com `json_repair`, que tolera as falhas comuns de LLM: cerca de markdown, vírgula sobrando, aspas trocadas.
2. Valida contra o modelo Pydantic `Compromisso` (`app/compromisso.py:39`).
3. Checa formato e coerência: data `AAAA-MM-DD`, horário `HH:MM`, **e rejeita data no passado**.
4. Falhou? Devolve `(False, "mensagem de erro")`, o erro vai para o estado e a aresta condicional **manda o fluxo de volta ao nó `interpretar`** — até `MAX_TENTATIVAS` execuções (`app/graph/estado.py:20`, hoje 3: a primeira mais duas correções). Na reexecução a saída reprovada e o motivo entram na conversa com a LLM (`_conversar()`, `app/graph/nos.py:54`), então o agente vê o próprio erro em vez de tentar de novo no escuro.
5. Esgotou as tentativas? O fluxo vai para `falha_extracao`, o compromisso fica nulo e o grupo recebe um pedido de reescrita. Melhor do que seguir com um dado que não passou na validação.
6. Passou? Devolve o JSON normalizado. É exatamente esse texto que o Agente 2 recebe.

É aqui que "quinta-feira" vira `2026-10-29` com segurança: o prompt passa a data de hoje como referência e o guardrail confere que o resultado é uma data real e futura.

---

## 3. Agente 2 — Coordenador de Cuidados

Persona em `app/agents/coordenador.py`, instruções em `PROMPT_COORDENAR` (`app/graph/prompts.py:60`), execução no nó `coordenar()` (`app/graph/nos.py:128`).

Ele só roda quando `classificacao` é `cuidado`. Nos outros dois casos o grafo desvia para `resposta_fixa` e ele nem é chamado.

- **Entrada:** a saída do Agente 1 — o JSON, lido do campo `compromisso` do estado
- **Trabalho:** resumir o que foi entendido e perguntar o que falta
- **Saída:** um texto curto, até 4 frases, em português

O output do Agente 1 é o input do Agente 2. Ele **não vê a mensagem original** — só os dados já extraídos e validados. Isso é de propósito: assim ele não pode "reinterpretar" e reintroduzir um detalhe que o Agente 1 descartou.

```text
O compromisso e uma consulta de cardiologia para Dona Helena,
dia 05 de novembro de 2026, as 15:00, na clinica do centro.
Quem podera acompanha-la nesse dia?
```

Enquanto a tool não confirmar uma gravação, o texto não pode dizer "está marcada": `marcada` está no regex do `validar_resposta` e a resposta é rejeitada.

Três obrigações:

- **Pedir o que falta.** Se `data` ou `horario` estão nulos, pergunta. Se não há `responsavel`, pergunta quem pode acompanhar — e **nunca escolhe alguém**.
- **Escrever a data por extenso.** O compromisso chega com dois campos: `data` em `AAAA-MM-DD`, que é o que a tool aceita, e `data_por_extenso`, que é o que vai no texto. O agente copia cada uma; não recalcula nenhuma.
- **Não mentir sobre agendamento.** Só pode afirmar que gravou se a tool devolver confirmação.

### A tool `agenda`

`app/tools/agenda.py`, anexada ao agente 2 no nó `coordenar` via `bind_tools`. **Quem decide chamá-la é a LLM**, no meio da resposta, como era no CrewAI. Quatro ações: `criar`, `consultar`, `alterar`, `deletar`.

```text
compromisso no prompt → LLM decide chamar → tool grava ou recusa
                      → LLM conta ao grupo → guardrail confere
```

Teto de 2 voltas (`MAX_CHAMADAS`). O retorno da tool fica em `gravacao`, no estado — é a única prova de que algo foi gravado.

O agente escolhe a ação e os campos, **nunca SQL**. E como quem preenche os argumentos é uma LLM, toda escrita é verificada dentro da tool antes de ir ao banco:

| Verificação | Efeito |
| --- | --- |
| `tipo`, `pessoa_idosa`, `data`, `horario` presentes | sem isso, recusa |
| **`responsavel` presente** | sem isso, recusa e manda perguntar ao grupo |
| data em `AAAA-MM-DD`, existente no calendário, não no passado | recusa |
| mesmo tipo + pessoa + data + horário já ativo | recusa como duplicata |
| `deletar` | vira `status = 'cancelado'`; a linha não some |

A exigência de `responsavel` **não vinha da branch `agente_tool`** — foi acrescentada aqui. Sem ela o compromisso era gravado assim que tivesse data e hora, antes de alguém aceitar acompanhar, o que contraria o `CLAUDE.md` §6: _o sistema não deve decidir sozinho quem será obrigado a levar a pessoa idosa_.

#### Onde os compromissos ficam

`app/tools/banco.py` escolhe o banco pela `DATABASE_URL` — é o único arquivo que sabe que há dois:

| `DATABASE_URL` | Banco | Precisa instalar |
| --- | --- | --- |
| começa com `postgresql://` | o container do `compose.yml` | Docker + `psycopg[binary]` |
| não definida | `dados/agenda.sqlite` | nada |

O SQL é escrito uma vez com `?`, e o marcador vira `%s` no Postgres. Os dois caminhos ficam exercitados porque o time usa os dois.

### Guardrail `validar_resposta`

Em `app/compromisso.py`, chamado pelo nó de mesmo nome. Procura "agendei", "marquei", "registrei", "criado", "cadastrei", "coloquei na agenda" — **e só reprova quando a tool não confirmou nada** nesta mensagem. Rejeitou? A aresta condicional manda o fluxo de volta ao `coordenar` com o motivo, como no guardrail do Agente 1.

O que decide é o campo `gravacao` do estado, preenchido com o retorno da tool — **não o que a LLM diz ter feito**. É o `CLAUDE.md` §4: _nunca informar que agendou se a API não confirmar a criação_.

> Na branch `agente_tool` esse guardrail contradizia a instrução dada ao agente: ele mandava informar o resultado da tool e ao mesmo tempo barrava as palavras para isso. Escapava por uma brecha — "criado" não estava na lista.

---

## 4. `app/compromisso.py` — a metade sem IA

Os três agentes compartilham este arquivo. Ele não chama LLM nenhuma: é Python comum, com Pydantic e expressões regulares. Mesma entrada, mesma saída, sempre.

A divisão de responsabilidade entre os dois arquivos é a ideia central do projeto:

> O prompt, em `graph/prompts.py`, **pede** para o agente não adivinhar. O `compromisso.py` **verifica** que ele não adivinhou.

Pedido é sugestão — um prompt pode ser ignorado por uma LLM num dia ruim. Verificação é garantia.

### O contrato de dados

A classe `Compromisso` (`app/compromisso.py:39`) declara quais campos existem e de que tipo. Se a LLM inventar um campo ou trocar um tipo, a falha aparece aqui, não três camadas adiante.

```python
OBRIGATORIOS = ("tipo", "pessoa_idosa", "data", "horario")
```

São os quatro campos sem os quais o compromisso não poderá ser agendado mais tarde. `local`, `especialidade` e `responsavel` ficam de fora de propósito: a falta deles não impede o agendamento, só exige uma pergunta ao grupo.

### Os dois guardrails

| Função | Valida a saída de | Rejeita |
| --- | --- | --- |
| `validar_extracao` (`:116`) | Agente 1 | JSON malformado, campo inválido, data fora do formato, **data no passado** |
| `validar_resposta` (`:163`) | Agente 2 | resposta vazia ou curta demais; texto que afirme ter agendado, marcado ou registrado |

Ambos devolvem `(True, saida_normalizada)` ou `(False, "explicação do erro")`. No segundo caso a aresta condicional **devolve o fluxo ao nó do agente** com a explicação no estado, até o limite de `MAX_TENTATIVAS`.

Exemplo concreto: a LLM interpreta "quinta-feira" como uma data que já passou. O guardrail barra e responde ao agente _"data no passado: 2026-10-22"_. Ele recalcula com essa informação.

Detalhamento de cada um nas seções [§2](#2-agente-1--intérprete-de-compromissos) e [§3](#3-agente-2--coordenador-de-cuidados).

### Utilitários

| Função | Para quê |
| --- | --- |
| `hoje()` | data corrente no fuso de São Paulo — referência para "amanhã", "quinta-feira" |
| `faltantes()` | quais campos obrigatórios ainda estão vazios; usado por `app/routes/agente.py` |
| `interpretar_json()` | lê o JSON da LLM tolerando cerca de markdown, vírgula sobrando e aspas trocadas |
| `data_por_extenso()` | converte `2026-11-11` em "11 de novembro de 2026" para a resposta ao grupo |

`data_por_extenso()` existe por causa de um erro observado: a conversão era regra de prompt e a LLM trocava o dia — o compromisso trazia `2026-11-11` e a resposta saía "07 de novembro de 2026". Escrever a data é conversão mecânica, não julgamento; em código o resultado é sempre o mesmo. O prompt do Agente 2 agora só manda copiar o que já vem pronto.

### Por que mora fora do `graph/`

Três razões práticas:

1. **Testável sem LLM.** Dá para verificar toda a lógica de validação sem gastar uma chamada à API nem depender da variação de temperatura do modelo.
2. **Um lugar só.** Os dois nós de guardrail e a rota da API usam as mesmas regras. Duplicar daria divergência.
3. **Sobrevive à troca de framework.** O arquivo não importa nada de framework de agentes. Isso deixou de ser teoria: na migração de CrewAI para LangGraph, `compromisso.py` atravessou praticamente intacto — só os docstrings mudaram. Toda a parte que impede o sistema de inventar dado continuou valendo.

---

## 5. Por que três agentes e não um

Papéis diferentes, falhas diferentes.

| Agente          | Como ele erra                        | O que pega o erro                                        |
| --------------- | ------------------------------------ | -------------------------------------------------------- |
| 1 — Intérprete  | Extrai dado errado, inventa data     | `validar_extracao`: Pydantic + formato + data no passado |
| 2 — Coordenador | Promete o que não fez, grava cedo    | `validar_resposta` + as checagens dentro da tool          |
| 3 — Consultor   | Responde saúde de memória, sem fonte | `validar_orientacao`: exige página citada, veta dose     |

Um agente único misturaria tudo num prompt só, e qualquer validação teria que adivinhar qual parte falhou. Separando, cada guardrail sabe exatamente o que está checando e a aresta de retry devolve o fluxo só à etapa quebrada.

O 3 é separado do 2 por um motivo a mais: as personas se contradizem. O Coordenador existe para **não** opinar sobre saúde; o Consultor existe para repassar o que o material de saúde diz. Numa persona só, seriam ordens opostas para a mesma LLM.

Atende com folga o requisito acadêmico de **pelo menos dois agentes de IA colaborando** (`CLAUDE.md` §9).

---

## 6. Como rodar

Dois processos, em dois terminais.

### Terminal 1 — API dos agentes

Na raiz do projeto (`challenge-2/`):

```bash
# Bash / Git Bash
./.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000
```

```powershell
# PowerShell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

Confirme com `curl http://localhost:8000/saude` → `{"status":"ok"}`.

Por padrão o terminal mostra só metadados — se identificou compromisso e quais campos faltam. O conteúdo da conversa **não vai para o log**: são dados de saúde e dados pessoais (`CLAUDE.md` §8). Para ver tudo durante o desenvolvimento:

```bash
DEBUG_AGENTES=1 ./.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000
```

### Terminal 2 — Bot do WhatsApp

```bash
cd whatsapp-bot
node bot.js
```

Na primeira vez aparece um QR code no terminal — leia com o WhatsApp do celular. A sessão fica salva em `whatsapp-bot/auth/`.

### Rodar os agentes sem WhatsApp

Com a API no ar, dá para chamar direto, sem o bot:

```bash
curl -X POST http://localhost:8000/agente \
  -H "Content-Type: application/json" \
  -d '{"mensagem": "a vo Helena tem consulta no cardiologista quinta as 15h", "data_mensagem": "2026-10-29"}'
```

Todos os comandos rodam **da raiz do projeto**. É de lá que o `.env` é encontrado e que o pacote `app` fica importável — rodar de dentro de `app/` faz o `load_dotenv()` não achar a chave, e a falha só aparece na primeira chamada ao Groq.

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

- **Calendário de verdade.** Os compromissos são gravados numa tabela própria, não numa agenda que a pessoa abre no celular. Google Calendar e Outlook continuam em aberto — `CLAUDE.md` §10.
- **Resolver o conflito pela conversa.** Quando a mensagem nova contradiz o combinado, o assistente pergunta se é remarcação ou compromisso novo — mas **não há como responder**. Dizer "é remarcação" na mensagem seguinte gera outra extração, que esbarra no mesmo conflito. Falta um caminho que leia a resposta do grupo e aplique a decisão. É a maior lacuna de hoje.

- **Mais de um compromisso aberto por grupo.** O thread guarda um só. Duas consultas em aberto ao mesmo tempo caem no caminho do conflito, uma de cada vez. Suportar vários exige identificador por compromisso, não por grupo — `CLAUDE.md` §4 e §7.7.

- **"É outro compromisso" descarta o segundo.** Quando o grupo nega a remarcação — "não, é outro exame" —, o sistema mantém o compromisso antigo e **joga fora o novo, em silêncio**. O certo seria abrir um segundo compromisso, mas o thread guarda um só. Mesma raiz do item abaixo.

- **Consultar compromisso antigo pela conversa.** O `!compromisso` já lista o que está gravado, mas perguntar "quando é a consulta da vó?" em texto livre ainda cai como `conversa`: não existe intenção de consulta no grafo. A tool tem a ação `consultar` e o agente 2 pode chamá-la, mas só no caminho do `!agenda`.

- **Expurgo de conversa abandonada.** Grupo que começa um compromisso e nunca termina mantém o thread para sempre — o `delete_thread` só roda quando encerra. Varrer por idade exigiria listar threads por data, que o `SqliteSaver` não expõe.
- **Atualização e cancelamento.** Remarcação é detectada (vira conflito) mas não aplicada; cancelamento não é reconhecido. `CLAUDE.md` §7 item 7.
- **Rede neural.** O requisito `CLAUDE.md` §9 pede uma. Hoje a classificação "é compromisso ou não" é feita pela LLM, no campo `classificacao` — não por um modelo treinado pela equipe.
- **Autorização.** Não há checagem de quem pode acionar o comando, nem de permissão de acesso à agenda de alguém. `CLAUDE.md` §6 e §11.7.
- **MLOps.** Requisito `CLAUDE.md` §9, ainda não iniciado. A base de conhecimento, do mesmo item, existe desde o Agente 3.
- **Índice do Guia persistido.** É remontado a cada vez que a API sobe. Salvar em disco cortaria o tempo de startup, mas exige versionar o índice ou gerá-lo num passo à parte.
- **Sair da `langchain-community`.** O Agente 3 a usa só pelo `PyPDFLoader`, e a própria LangChain está descontinuando o pacote. Trocar por `pypdf` direto são ~10 linhas.

---

## 9. Dependências externas

- **LLM:** `openai/gpt-oss-20b`, via Groq, pelo `langchain-groq`. Chave em `.env` (`GROQ_API_KEY`), carregada por `load_dotenv()`. O modelo pode ser trocado por `GROQ_MODEL` no ambiente.
- **`max_tokens=2000`** (`app/graph/nos.py:46`) não é folga: o `gpt-oss-20b` é modelo de raciocínio e gasta parte dos tokens no raciocínio interno. Com limite curto não sobra nada para a resposta e o conteúdo chega vazio.
- **`reasoning_format="hidden"`** no mesmo lugar. Sem isso o raciocínio do modelo vem junto no campo de conteúdo, o JSON do Agente 1 chega misturado a texto solto e o guardrail reprova uma saída que estava correta.
- **Banco da agenda:** SQLite por padrão (`dados/agenda.sqlite`, nada a instalar) ou PostgreSQL 16 pelo `compose.yml`, se `DATABASE_URL` estiver definida. O `psycopg[binary]` é opcional e só o segundo caso precisa dele.
- **Embeddings:** `intfloat/multilingual-e5-base`, pelo `sentence-transformers`, rodando **local**. Nenhuma pergunta do grupo sai da máquina para ser indexada. São ~1 GB entre modelo e `torch`, baixados do HuggingFace na primeira execução.
- **LangGraph 1.2.20**, **langchain-groq 1.1.3**, **Baileys 7.0.0-rc14** (WhatsApp), **FastAPI/uvicorn**.
- O parse do JSON fica em `compromisso.py`, e não numa saída estruturada do framework: ele é a fronteira entre a LLM e o resto do sistema, e precisa valer igual qualquer que seja o framework por baixo.

---

## 10. Documentação do LangGraph

Versão em uso: **langgraph 1.2.20**.

### Estrutura e sintaxe

| Página | O que cobre |
| --- | --- |
| [Graph API — control flow](https://docs.langchain.com/oss/python/langgraph/graph-api-control-flow) | sequências, ramificações, **arestas condicionais** e ciclos — a base do que está em `grafo.py` |
| [`StateGraph.add_conditional_edges`](https://reference.langchain.com/python/langgraph/graph/state/StateGraph/add_conditional_edges) | assinatura exata do método que faz o roteamento e o retry |
| [Send e Command](https://docs.langchain.com/oss/python/langgraph/graph-api-send-command) | retornar a rota de dentro do nó, em vez de uma função de aresta separada |

### Persistência — o caminho da memória entre mensagens

| Página | O que cobre |
| --- | --- |
| [Persistence](https://docs.langchain.com/oss/python/langgraph/persistence) | checkpointer, `thread_id` e retomada de conversa |
| [Checkpointers](https://docs.langchain.com/oss/python/integrations/checkpointers) | os backends disponíveis — memória, SQLite, Postgres, Mongo, Redis |

**Armadilha verificada:** o `SqliteSaver` **não implementa** `prune()`, `delete_for_runs()` nem `copy_thread()` — os três existem na classe base e levantam `NotImplementedError`. O único método de limpeza que funciona é `delete_thread(thread_id)`. Vale conferir antes de planejar em cima de qualquer um deles.

### Por onde começar

[Graph API — control flow](https://docs.langchain.com/oss/python/langgraph/graph-api-control-flow). É a página que explica as duas peças centrais daqui: a aresta condicional que roteia por `classificacao` e o ciclo que devolve o fluxo ao agente quando o guardrail reprova.

### Decisão em aberto

O checkpointer é o `SqliteSaver`, com o banco em `dados/conversas.sqlite` (`app/graph/grafo.py:97`). Serve ao protótipo, mas é arquivo local: não sobrevive a deploy em mais de um processo nem tem replicação. Se o projeto sair da máquina de desenvolvimento, a escolha entre Postgres e outro backend volta à mesa — e junto com ela a retenção dos dados de saúde (`CLAUDE.md` §8). Decisão pendente.

---

## 11. Histórico de migração

O projeto nasceu em **CrewAI 1.15.28** e migrou para **LangGraph 1.2.20**. O que mudou e o que não mudou:

| Antes (CrewAI) | Depois (LangGraph) |
| --- | --- |
| `Crew(process=sequential)` com duas `Task` | grafo com nós e arestas condicionais |
| `Task(context=[anterior])` | campo `compromisso` no `EstadoGrupo` |
| `guardrail=` + `guardrail_max_retries=2` | nó de validação + aresta que volta ao agente, limitada por `MAX_TENTATIVAS` |
| Agente 2 respondia até quando não era cuidado | nó `resposta_fixa`, sem LLM |
| `montar_crew()` a cada pedido | grafo compilado uma vez, estado por `invoke` |
| `LLM` do CrewAI, via litellm | `ChatGroq`, direto |
| Memória bloqueada por conflito `mcp` | conflito eliminado; falta decidir o checkpointer |

`app/compromisso.py` atravessou a migração praticamente intacto — só os docstrings mudaram. Era o objetivo declarado na §4: a parte que impede o sistema de inventar dado não depende de framework.

Dois parâmetros do CrewAI não têm equivalente e foram descartados: `max_rpm` (controle de taxa, que passa a ser responsabilidade do cliente HTTP ou do Groq) e `max_iter` (número de passos internos do agente, que no grafo é explícito nas arestas).
