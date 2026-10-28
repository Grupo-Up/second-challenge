# Comandos

Cola rápida. Tudo a partir da raiz do projeto (`challenge-2/`).

> **Bash usa `/`, PowerShell usa `\`.** No Bash a barra invertida é escape: `.\.venv\Scripts\python.exe` vira `..venvScriptspython.exe` e falha.

---

## Ligar o sistema completo

Dois terminais, nesta ordem.

### Terminal 1 — API

```bash
./.venv/Scripts/python.exe -m uvicorn api:app --reload --port 8000
```

```powershell
.\.venv\Scripts\python.exe -m uvicorn api:app --reload --port 8000
```

Pronto quando aparecer `Uvicorn running on http://127.0.0.1:8000`.

### Terminal 2 — Bot do WhatsApp

```bash
cd whatsapp-bot
node bot.js
```

Pronto quando aparecer `Bot conectado ao WhatsApp!`. Na primeira vez lê o QR code com o celular.

**Testando com o seu próprio número?** O bot ignora as próprias mensagens. Suba assim:

```bash
RESPONDER_PROPRIAS=1 node bot.js
```

```powershell
$env:RESPONDER_PROPRIAS = "1"; node bot.js
```

### No grupo do WhatsApp

```text
!ping                          → testa se o bot escuta
!agenda <mensagem>             → aciona o agente
```

Exemplo: `!agenda a vo Helena tem consulta no cardiologista quinta as 15h`

---

## Sem WhatsApp

### Verificar a fiação — sem gastar LLM, roda em 1 segundo

```bash
./.venv/Scripts/python.exe verificar.py
```

Rode depois de mexer nos `.jsonc` ou de atualizar o CrewAI.

### Testar a API direto

```bash
curl http://localhost:8000/saude

curl -X POST http://localhost:8000/agente \
     -H "Content-Type: application/json" \
     -d '{"mensagem":"a vo Helena tem consulta quinta as 15h","grupo_id":"teste"}'
```

A resposta traz `resposta`, `compromisso` (o JSON estruturado) e `faltantes` — é tudo que o bot recebe.

**Testar a memória:** mande duas chamadas com o **mesmo** `grupo_id`:

```bash
# 1
-d '{"mensagem":"a vo Helena tem consulta quinta as 15h","grupo_id":"teste"}'
# 2 — tem que completar a anterior, nao criar outra
-d '{"mensagem":"eu levo ela","grupo_id":"teste"}'
```

Sem `grupo_id`, cada chamada é independente.

No PowerShell use `curl.exe`, não `curl` — o alias do PowerShell é outro comando.

---

## Nada acontece. E agora?

Na ordem:

| # | Checar | Como |
| --- | --- | --- |
| 1 | A API está de pé? | `curl http://localhost:8000/saude` → `{"status":"ok"}` |
| 2 | O agente funciona? | o `curl` do `POST /agente` acima |
| 3 | O bot escuta o grupo? | mande `!ping` no grupo |
| 4 | A mensagem começa com `!agenda`? | mensagem comum é ignorada de propósito |
| 5 | Está mandando do próprio número? | suba com `RESPONDER_PROPRIAS=1` |
| 6 | É um grupo mesmo? | conversa direta é descartada sem logar nada |

Os passos 5 e 6 descartam a mensagem **antes** do log — o terminal fica mudo e parece que o bot caiu.

---

## Desenvolvimento

### Ver o conteúdo das mensagens no log da API

```bash
DEBUG_AGENTES=1 ./.venv/Scripts/python.exe -m uvicorn api:app --reload --port 8000
```

```powershell
$env:DEBUG_AGENTES = "1"; .\.venv\Scripts\python.exe -m uvicorn api:app --reload --port 8000
```

**Só em desenvolvimento, com dados fictícios.** Por padrão o log mostra apenas metadados — são dados de saúde (`CLAUDE.md` §8).

### Matar um processo preso na porta 8000

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen | Select-Object OwningProcess
Stop-Process -Id <PID>
```

---

## Instalação, do zero

```bash
python -m venv .venv
./.venv/Scripts/python.exe -m pip install crewai fastapi uvicorn python-dotenv json-repair pydantic

cd whatsapp-bot && npm install && cd ..
```

Mais um `.env` na raiz com a chave do Groq:

```ini
GROQ_API_KEY=sua_chave_aqui
```

---

## Git

```bash
git status --short
git switch -c <nome-da-branch>
git log --oneline -5
```

Branch atual: `refactor/crewai-jsonc`.
