# Alterações: Agente 2 e agenda

## Objetivo

A funcionalidade que seria implementada como um Agente 3 separado foi
transformada em uma tool usada diretamente pelo Agente 2, o coordenador.

O Agente 2 continua responsável por conversar com o grupo, mas agora pode
usar a tool de agenda para executar operações confirmadas no PostgreSQL.

## Arquivos alterados

### `app/agents/coordenador.py`

O coordenador passou a receber a `AgendaTool`:

```python
tools=[AgendaTool()]
```

Assim, a tool fica disponível para o CrewAI durante a execução do Agente 2.

### `app/tools/agenda.py`

Novo arquivo com a implementação da tool de agenda.

Responsabilidades:

- conectar ao PostgreSQL usando `DATABASE_URL`;
- criar a tabela `compromissos` quando necessário;
- validar campos obrigatórios;
- rejeitar datas passadas;
- evitar compromissos duplicados;
- executar operações SQL parametrizadas;
- manter o histórico de compromissos cancelados.

Operações disponíveis:

| Ação | Descrição |
| --- | --- |
| `criar` | Cria um compromisso ativo |
| `consultar` | Consulta compromissos ativos |
| `alterar` | Atualiza um compromisso existente |
| `deletar` | Marca o compromisso como cancelado |

O Agente 2 não recebe acesso a SQL livre. Ele chama apenas as operações
definidas pela tool.

### `app/crews/crew.py`

As instruções da tarefa do coordenador foram atualizadas para:

- usar a tool somente quando a ação estiver confirmada;
- não inventar dados ausentes;
- pedir esclarecimentos quando faltarem dados obrigatórios;
- informar uma alteração somente depois da confirmação retornada pela tool.

### `compose.yml`

Novo arquivo para executar o PostgreSQL pelo Docker:

- imagem: PostgreSQL 16;
- banco: `agenda`;
- usuário: `agenda_app`;
- porta local: `5432`;
- volume persistente: `postgres_data`.

### `requirements.txt`

Foi adicionada a dependência do PostgreSQL para Python:

```text
psycopg[binary]
```

As demais dependências do projeto também foram documentadas nesse arquivo.

### Documentação

O [README.md](../README.md) e o
[ARQUITETURA.md](ARQUITETURA.md) foram atualizados para refletir que a
agenda agora é uma tool do Agente 2.

## Fluxo atualizado

```text
Mensagem do WhatsApp
        ↓
Agente 1: interpreta e extrai o compromisso
        ↓
Agente 2: coordena a resposta
        ↓
AgendaTool: cria, consulta, altera ou cancela no PostgreSQL
        ↓
Agente 2: responde ao grupo com o resultado confirmado
```

## Como executar

Na raiz do projeto:

```bash
docker compose up -d
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --reload --port 8000
```

O endereço padrão usado pela tool é:

```text
postgresql://agenda_app:agenda_dev_password@localhost:5432/agenda
```

É possível substituir esse endereço pela variável de ambiente
`DATABASE_URL`.

## Limitações atuais

- O PostgreSQL precisa estar disponível antes da tool executar operações.
- Ainda não existe autorização individual por usuário.
- Ainda não há integração com Google Calendar ou Outlook.
- O fluxo depende de confirmação suficiente dos dados antes de alterar a
  agenda.
- O teste completo contra o banco depende do Docker estar funcionando e
  acessível pelo usuário atual.
