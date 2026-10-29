
"""Endpoints que expoem os agentes ao bot do WhatsApp.

O bot envia a mensagem do grupo e recebe de volta a resposta ao grupo e o
compromisso estruturado.
"""

import os
from typing import Optional

from fastapi import APIRouter
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