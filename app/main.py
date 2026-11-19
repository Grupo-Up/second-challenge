
"""Inicializacao da API.

Sobe com:
    python -m uvicorn app.main:app --reload --port 8000

O comando roda a partir da raiz do projeto: e de la que o .env e
encontrado e que o pacote app fica importavel.
"""

import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.agents import RAG
from app.queda import servico as detector_de_quedas
from app.routes import agente, sensor

# O console do Windows usa cp1252 e quebra nos caracteres tipograficos
# que a LLM costuma devolver
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


@asynccontextmanager
async def ciclo_de_vida(_app: FastAPI):
    """Monta o indice do Guia antes de a API atender o primeiro pedido.

    Deixar para a primeira pergunta faria alguem do grupo esperar minutos
    sem resposta. Falhar aqui nao derruba a API: sem o Guia, so o !duvida
    para de funcionar.
    """
    try:
        RAG.get_vector_store()
    except Exception as erro:
        print("falha ao montar o Guia do Cuidador:", type(erro).__name__, flush=True)

    # Sem modelo em modelos/queda/, so o detector de quedas fica desligado
    detector_de_quedas.iniciar()
    if not os.environ.get("QUEDA_TOKEN"):
        print("aviso: QUEDA_TOKEN nao definido, rotas do detector sem protecao", flush=True)

    yield


app = FastAPI(
    title="Agentes de apoio aos cuidados de idosos",
    lifespan=ciclo_de_vida,
)

app.include_router(agente.router)
app.include_router(sensor.router)