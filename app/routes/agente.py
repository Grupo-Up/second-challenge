
"""Endpoints que expoem os agentes ao bot do WhatsApp.

O bot envia a mensagem do grupo e recebe de volta a resposta ao grupo e o
compromisso estruturado.
"""

import os
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from app.compromisso import faltantes
from app.graph.grafo import processar

# Com DEBUG_AGENTES=1 o terminal mostra o compromisso e a resposta.
# Desligado por padrao: sao dados de saude e dados pessoais, que nao
# devem ficar em log (CLAUDE.md, secao 8).
DEBUG = os.environ.get("DEBUG_AGENTES") == "1"

router = APIRouter()


class Entrada(BaseModel):
    mensagem: str
    # Data da mensagem, base para interpretar "amanha" e "quinta-feira"
    data_mensagem: Optional[str] = None
    # Identificador da conversa - no WhatsApp, o JID do grupo. E o que
    # separa o compromisso de uma familia do de outra.
    grupo: Optional[str] = None
    # Nome de quem escreveu, para resolver "eu levo ela". Nao vai para o
    # log: e dado pessoal (CLAUDE.md, secao 8).
    autor: Optional[str] = None
    # Comando usado no grupo: agenda, compromisso ou andamento
    comando: Optional[str] = "agenda"


@router.get("/saude")
def saude():
    return {"status": "ok"}


@router.post("/agente")
def rodar(entrada: Entrada):
    print("\n--- pedido recebido, executando os agentes ---", flush=True)

    resultado = processar(
        entrada.mensagem,
        entrada.data_mensagem,
        entrada.grupo,
        entrada.autor,
        entrada.comando,
    )

    compromisso = resultado["compromisso"]
    pendentes = faltantes(compromisso) if compromisso else []

    # Sem DEBUG, registra apenas metadados: nada do conteudo da conversa
    print(
        "classificacao:",
        resultado.get("classificacao") or "desconhecida",
        "| campos ausentes:",
        ", ".join(pendentes) if pendentes else "nenhum",
        "| compromisso encerrado:",
        "sim" if resultado.get("encerrado") else "nao",
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