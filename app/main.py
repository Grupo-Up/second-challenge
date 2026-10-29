
"""Inicializacao da API.

Sobe com:
    python -m uvicorn app.main:app --reload --port 8000

O comando roda a partir da raiz do projeto: e de la que o .env e
encontrado e que o pacote app fica importavel.
"""

import sys

from fastapi import FastAPI

from app.routes import agente

# O console do Windows usa cp1252 e quebra nos caracteres tipograficos
# que a LLM costuma devolver
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

app = FastAPI(title="Agentes de apoio aos cuidados de idosos")

app.include_router(agente.router)