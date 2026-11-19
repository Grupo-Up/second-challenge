"""Endpoints do detector de quedas.

    POST /sensor/sensorlogger   recebe o streaming HTTP do Sensor Logger
    GET  /sensor/situacao       modelo carregado, versao, limiar
    POST /dispositivos          liga um relogio a um grupo e a uma pessoa
    GET  /alertas/pendentes     o bot busca os alertas a enviar
    POST /alertas/{id}/enviado  o bot confirma que enviou
    POST /alertas/retorno       "!queda ok" / "!queda falso" do grupo
    GET  /alertas/resumo        alertas por status (metrica de producao)

A logica fica em app/queda/servico.py e app/queda/alertas.py.

Protecao: com QUEDA_TOKEN definido no .env, toda chamada precisa do
token, no cabecalho "Authorization: Bearer <token>" ou em ?token=<token>
(o Sensor Logger aceita a URL com o token). Sem isso, quem descobrir o
endereco do tunel (ngrok) poderia ler os alertas, que trazem o nome da
pessoa idosa, ou forjar uma queda.
"""

import hmac
import os
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.queda import alertas, servico


def verificar_token(
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Query(None),
):
    esperado = os.environ.get("QUEDA_TOKEN")
    if not esperado:
        return  # desenvolvimento local; a API avisa ao subir
    recebido = token or (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(recebido.encode(), esperado.encode()):
        raise HTTPException(401, "token invalido")


router = APIRouter(dependencies=[Depends(verificar_token)])


@router.post("/sensor/sensorlogger")
def receber_sensorlogger(
    corpo: Any = Body(...),
    dispositivo: Optional[str] = Query(None, description="sobrepoe o deviceId do lote"),
):
    codigo, resposta = servico.processar_lote(corpo, dispositivo)
    return JSONResponse(resposta, status_code=codigo)


@router.get("/sensor/situacao")
def situacao():
    return servico.situacao()


class Vinculo(BaseModel):
    dispositivo: str
    grupo: str
    pessoa_idosa: str


@router.post("/dispositivos")
def vincular(vinculo: Vinculo):
    alertas.vincular(vinculo.dispositivo, vinculo.grupo, vinculo.pessoa_idosa)
    return {"ok": True}


@router.get("/alertas/pendentes")
def pendentes():
    return alertas.pendentes()


@router.post("/alertas/{alerta_id}/enviado")
def enviado(alerta_id: int):
    if not alertas.marcar_enviado(alerta_id):
        raise HTTPException(404, "alerta inexistente ou ja enviado")
    return {"ok": True}


class Retorno(BaseModel):
    grupo: str
    foi_queda: bool


@router.post("/alertas/retorno")
def retorno(dados: Retorno):
    alerta = alertas.registrar_retorno(dados.grupo, dados.foi_queda)
    if alerta is None:
        raise HTTPException(404, "nenhum alerta de queda em aberto neste grupo")
    return {"ok": True, "status": alerta["status"]}


@router.get("/alertas/resumo")
def resumo():
    return alertas.resumo_retornos()
