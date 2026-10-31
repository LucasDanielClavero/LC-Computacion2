"""
La API HTTP (FastAPI).

POST responde INMEDIATAMENTE: solo encola y devuelve el id con estado
inicial. Nunca espera a que la tarea termine (esa es la idea del TP).
"""

import glob
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from gestor import ESTADOS_POSIBLES, GestorTareas, TIPOS_VALIDOS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Arranca y apaga el gestor junto con la app."""
    # Al arrancar: reporto si hay volcados previos (consigna 4)
    volcados_previos = sorted(glob.glob("volcados/estado_*.json"))
    if volcados_previos:
        logging.info("Se encontraron volcados previos (el estado anterior NO se recarga): %s",
                     ", ".join(volcados_previos))

    gestor = GestorTareas()
    await gestor.iniciar()
    app.state.gestor = gestor

    yield  # la app corre mientras estamos aca

    # Al apagar (SIGTERM / SIGINT): apagado ordenado + volcado de estado
    await gestor.apagar()


app = FastAPI(title="Plataforma de Tareas Distribuidas", version="0.1", lifespan=lifespan)


# ---------------------------------------------------------------
# Modelos de entrada (pydantic valida la forma del body)
# ---------------------------------------------------------------
class PeticionTarea(BaseModel):
    tipo: str
    params: dict = {}
    timeout_s: Optional[float] = None


# ---------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------
@app.post("/tareas")
async def crear_tarea(peticion: PeticionTarea):
    if peticion.tipo not in TIPOS_VALIDOS:
        raise HTTPException(
            status_code=400,
            detail=f"tipo desconocido: '{peticion.tipo}'. Tipos validos: {list(TIPOS_VALIDOS)}",
        )
    try:
        tarea = app.state.gestor.encolar(peticion.tipo, peticion.params, peticion.timeout_s)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # Respondo ya: id + estado inicial. La tarea todavia no empezo.
    return {"id": tarea["id"], "estado": tarea["estado"], "tipo": tarea["tipo"]}


@app.get("/tareas")
async def listar_tareas(estado: Optional[str] = Query(default=None)):
    if estado and estado not in ESTADOS_POSIBLES:
        raise HTTPException(
            status_code=400,
            detail=f"estado desconocido: '{estado}'. Estados validos: {list(ESTADOS_POSIBLES)}",
        )
    return app.state.gestor.listar(estado)


@app.get("/tareas/{id_tarea}")
async def obtener_tarea(id_tarea: str):
    tarea = app.state.gestor.obtener(id_tarea)
    if tarea is None:
        raise HTTPException(status_code=404, detail=f"no existe la tarea '{id_tarea}'")
    return tarea


@app.delete("/tareas/{id_tarea}")
async def cancelar_tarea(id_tarea: str):
    tarea = app.state.gestor.cancelar(id_tarea)
    if tarea is None:
        raise HTTPException(status_code=404, detail=f"no existe la tarea '{id_tarea}'")
    return {"id": tarea["id"], "estado": tarea["estado"]}


@app.get("/estadisticas")
async def estadisticas():
    return app.state.gestor.estadisticas()
