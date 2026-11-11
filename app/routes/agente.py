
"""Endpoints que expoem os agentes ao bot do WhatsApp.

O bot envia a mensagem do grupo e recebe de volta a resposta ao grupo e o
compromisso estruturado.
"""

import os
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.compromisso import faltantes
from app.crews.crew import processar

# Com DEBUG_AGENTES=1 o terminal mostra o compromisso e a resposta.
# Desligado por padrao: sao dados de saude e dados pessoais, que nao
# devem ficar em log (CLAUDE.md, secao 8).
DEBUG = os.environ.get("DEBUG_AGENTES") == "1"

router = APIRouter()


class Entrada(BaseModel):
    mensagem: str
    # Data da mensagem, base para interpretar "amanha" e "quinta-feira"
    data_mensagem: Optional[str] = None


class Duvida(BaseModel):
    pergunta: str


@router.get("/saude")
def saude():
    return {"status": "ok"}


@router.post("/agente")
def rodar(entrada: Entrada):
    print("\n--- pedido recebido, executando os agentes ---", flush=True)

    resultado = processar(entrada.mensagem, entrada.data_mensagem)

    compromisso = resultado["compromisso"]
    pendentes = faltantes(compromisso) if compromisso else []

    # Sem DEBUG, registra apenas metadados: nada do conteudo da conversa
    print(
        "classificacao:",
        (compromisso or {}).get("classificacao", "desconhecida"),
        "| campos ausentes:",
        ", ".join(pendentes) if pendentes else "nenhum",
        flush=True,
    )

    if DEBUG:
        print("\nCOMPROMISSO:", flush=True)
        for campo, valor in (compromisso or {}).items():
            print(f"  {campo}: {valor}", flush=True)

        print("\nRESPOSTA AO GRUPO:", flush=True)
        print(resultado["resposta"], flush=True)

    return {
        "resposta": resultado["resposta"],
        "compromisso": compromisso,
        "faltantes": pendentes,
    }


@router.post("/duvida")
def responder_duvida(entrada: Duvida):
    """Responde uma dúvida usando o Guia do Cuidador como fonte."""
    pergunta = entrada.pergunta.strip()
    if not pergunta:
        raise HTTPException(status_code=400, detail="A pergunta não pode ficar vazia.")

    try:
        from app.agents.RAG import pergunta_ao_agente

        return {"resposta": pergunta_ao_agente(pergunta)}
    except (FileNotFoundError, ImportError) as erro:
        raise HTTPException(
            status_code=503,
            detail="O RAG não está disponível. Instale as dependências e confira o PDF.",
        ) from erro