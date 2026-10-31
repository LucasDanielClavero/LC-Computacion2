"""
El gestor de tareas: el corazon del TP.
- Cola de tareas (asyncio.Queue): lo que ponen los endpoints, lo que consumen los workers.
- Pool de workers: N corrutinas que sacan tareas de la cola y las ejecutan.
- Registro: diccionario en memoria con el estado de cada tarea.
- Timeout y cancelacion de tareas en ejecucion.
"""

import asyncio
import json
import logging
import os
import time
from concurrent.futures import ProcessPoolExecutor
from itertools import count

from tareas import ejecutar_descargar, ejecutar_esperar, hashear_bloqueante

# Tipos de tarea que admitimos
TIPOS_VALIDOS = ("descargar", "hashear", "esperar")

# Configuracion por variables de entorno (con valores por defecto razonables)
NUM_WORKERS = int(os.environ.get("NUM_WORKERS", "3"))
NUM_PROCESOS = int(os.environ.get("NUM_PROCESOS", "2"))
TIMEOUT_DEFAULT = float(os.environ.get("TIMEOUT_DEFAULT", "60"))
LIMITE_APAGADO = float(os.environ.get("LIMITE_APAGADO", "10"))
DIR_VOLCADOS = "volcados"

ESTADOS_POSIBLES = ("pendiente", "ejecutando", "completada", "fallida", "cancelada")


class GestorTareas:
    def __init__(self):
        self.registro = {}       # id -> datos de la tarea (estado en memoria)
        self.cola = None         # asyncio.Queue: productores = endpoints, consumidores = workers
        self.workers = []        # las N corrutinas del pool
        self.en_curso = {}       # id -> asyncio.Task que esta ejecutando esa tarea
        self.pool_procesos = None  # ProcessPoolExecutor para las tareas CPU-bound
        self._contador = count(1)  # para generar ids: t1, t2, t3...

    # -----------------------------------------------------------
    # Arranque: se llama al levantar la API
    # -----------------------------------------------------------
    async def iniciar(self):
        os.makedirs(DIR_VOLCADOS, exist_ok=True)
        self.cola = asyncio.Queue()
        # pool de PROCESOS para el trabajo pesado de CPU (hashear).
        # En Linux usa fork, en macOS/Windows usa spawn (por eso el
        # arranque de la app esta protegido con if __name__ == "__main__").
        self.pool_procesos = ProcessPoolExecutor(max_workers=NUM_PROCESOS)
        for i in range(NUM_WORKERS):
            self.workers.append(asyncio.create_task(self._worker(i)))
        logging.info("Gestor listo: %d workers, %d procesos para CPU-bound",
                     NUM_WORKERS, NUM_PROCESOS)

    # -----------------------------------------------------------
    # Encolar una tarea nueva (la llama el POST /tareas)
    # Devuelve inmediatamente: no espera a que termine.
    # -----------------------------------------------------------
    def encolar(self, tipo, params, timeout_s=None):
        self._validar_params(tipo, params)

        id_tarea = f"t{next(self._contador)}"
        tarea = {
            "id": id_tarea,
            "tipo": tipo,
            "params": params,
            "estado": "pendiente",
            "timeout_s": timeout_s if timeout_s is not None else TIMEOUT_DEFAULT,
            "resultado": None,
            "error": None,
            "creada": time.time(),
            "empezo": None,
            "termino": None,
        }
        self.registro[id_tarea] = tarea
        # put_nowait: estamos dentro del event loop, es encolar sin esperar
        self.cola.put_nowait(id_tarea)
        logging.info("Encolada tarea %s (%s)", id_tarea, tipo)
        return tarea

    def _validar_params(self, tipo, params):
        """Valida los params de cada tipo ANTES de encolar (falla rapido)."""
        if tipo == "descargar":
            if not isinstance(params.get("urls"), list) or not params["urls"]:
                raise ValueError("'descargar' necesita {'urls': [...]} (lista no vacia)")
        elif tipo == "hashear":
            if not isinstance(params.get("texto"), str):
                raise ValueError("'hashear' necesita {'texto': str, 'iteraciones': int}")
            if not isinstance(params.get("iteraciones"), int) or params["iteraciones"] < 1:
                raise ValueError("'iteraciones' tiene que ser un entero >= 1")
        elif tipo == "esperar":
            if not isinstance(params.get("segundos"), (int, float)) or params["segundos"] < 0:
                raise ValueError("'esperar' necesita {'segundos': numero >= 0}")
        else:
            raise ValueError(f"tipo desconocido: {tipo}. Tipos validos: {TIPOS_VALIDOS}")

    # -----------------------------------------------------------
    # Worker: corrutina del pool. Vive hasta que le llega la
    # "pastilla" None (señal de apagado ordenado).
    # -----------------------------------------------------------
    async def _worker(self, numero):
        logging.info("Worker %d arranco", numero)
        while True:
            id_tarea = await self.cola.get()   # se queda esperando aqui
            try:
                if id_tarea is None:
                    break  # pastilla de apagado: termine mi vida

                tarea = self.registro[id_tarea]

                # Si fue cancelada mientras estaba pendiente, la salto
                if tarea["estado"] == "cancelada":
                    continue

                tarea["estado"] = "ejecutando"
                tarea["empezo"] = time.time()

                # La corro en un sub-task aparte. Por que? Porque si la
                # correra el worker " directamente", no habria forma de
                # cancelar SOLO la tarea sin matar al worker entero.
                futura = asyncio.create_task(self._correr_tarea(tarea))
                self.en_curso[id_tarea] = futura

                try:
                    # wait_for resuelve el timeout Y la cancelacion:
                    # si vence, cancela futura y lanza TimeoutError.
                    # si alguien cancela futura, cae en CancelledError.
                    tarea["resultado"] = await asyncio.wait_for(
                        futura, timeout=tarea["timeout_s"]
                    )
                    tarea["estado"] = "completada"
                except asyncio.TimeoutError:
                    tarea["estado"] = "fallida"
                    tarea["error"] = "timeout: supero los %.1f segundos" % tarea["timeout_s"]
                except asyncio.CancelledError:
                    # Por el DELETE /tareas/{id}
                    tarea["estado"] = "cancelada"
                except Exception as e:
                    # La tarea misma exploto (url malformada, params invalidos en un proceso, etc)
                    tarea["estado"] = "fallida"
                    tarea["error"] = repr(e)
                finally:
                    tarea["termino"] = time.time()
                    self.en_curso.pop(id_tarea, None)
                    logging.info("Tarea %s termino como %s", id_tarea, tarea["estado"])
            finally:
                self.cola.task_done()
        logging.info("Worker %d termino", numero)

    # -----------------------------------------------------------
    # Ejecuta la tarea segun su tipo y devuelve el resultado.
    # -----------------------------------------------------------
    async def _correr_tarea(self, tarea):
        tipo = tarea["tipo"]

        if tipo == "esperar":          # I/O simulado: corrutina normal
            return await ejecutar_esperar(tarea["params"])

        if tipo == "descargar":        # I/O real: corrutina normal
            return await ejecutar_descargar(tarea["params"])

        if tipo == "hashear":
            # CPU-bound: NO lo hacemos en el event loop. run_in_executor
            # manda el trabajo a un proceso aparte y nos da un await
            # que no congela la API mientras tanto.
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                self.pool_procesos,
                hashear_bloqueante,
                tarea["params"]["texto"],
                tarea["params"]["iteraciones"],
            )

    # -----------------------------------------------------------
    # Cancelacion (DELETE /tareas/{id})
    # -----------------------------------------------------------
    def cancelar(self, id_tarea):
        tarea = self.registro.get(id_tarea)
        if tarea is None:
            return None

        if tarea["estado"] == "pendiente":
            # La marco y listo: cuando el worker la saque de la cola,
            # la va a saltear porque ya no esta pendiente.
            tarea["estado"] = "cancelada"
            logging.info("Tarea %s cancelada (estaba pendiente)", id_tarea)

        elif tarea["estado"] == "ejecutando":
            # Esta en ejecucion: corto el asyncio.Task. La CancelledError
            # la recibe el worker que la esta esperando.
            self.en_curso[id_tarea].cancel()
            logging.info("Tarea %s cancelada (estaba ejecutando)", id_tarea)

        # si ya estaba completada/fallida/cancelada, no cambia nada
        return tarea

    # -----------------------------------------------------------
    # Consultas
    # -----------------------------------------------------------
    def listar(self, estado=None):
        tareas = list(self.registro.values())
        if estado:
            tareas = [t for t in tareas if t["estado"] == estado]
        return tareas

    def obtener(self, id_tarea):
        return self.registro.get(id_tarea)

    def estadisticas(self):
        totales = {estado: 0 for estado in ESTADOS_POSIBLES}
        tiempos_completadas = []
        for t in self.registro.values():
            totales[t["estado"]] += 1
            if t["estado"] == "completada" and t["empezo"] and t["termino"]:
                tiempos_completadas.append(t["termino"] - t["empezo"])

        return {
            "totales_por_estado": totales,
            "tareas_totales": len(self.registro),
            "tiempo_promedio_ejecucion_s": round(sum(tiempos_completadas) / len(tiempos_completadas), 3) if tiempos_completadas else None,
            "workers_ocupados": len(self.en_curso),
            "workers_totales": NUM_WORKERS,
        }

    # -----------------------------------------------------------
    # Apagado ordenado. Lo llama uvicorn antes de cerrar.
    # 1) Dejo de aceptar tareas nuevas (el endpoint ya no responde)
    # 2) Aviso a los workers con una pastilla None y espero con limite
    # 3) Si no termino a tiempo, cancelo lo que quedo corriendo
    # 4) Volteo el estado a volcados/estado_<timestamp>.json
    # -----------------------------------------------------------
    async def apagar(self):
        logging.info("Apagando: esparzo %d pastillas en la cola...", len(self.workers))

        for _ in self.workers:
            await self.cola.put(None)

        # Espero con limite a que los workers terminen lo que corren
        try:
            await asyncio.wait_for(asyncio.gather(*self.workers), timeout=LIMITE_APAGADO)
            logging.info("Todos los workers terminaron ordenadamente")
        except asyncio.TimeoutError:
            logging.warning("Los workers no terminaron en %.0fs: cancelo las tareas en curso", LIMITE_APAGADO)
            for id_tarea, futura in list(self.en_curso.items()):
                self.registro[id_tarea]["estado"] = "cancelada"
                futura.cancel()
            await asyncio.gather(*self.en_curso.values(), return_exceptions=True)

            # ahora si, ya sin tareas, los workers se van a tomar la pastilla
            for w in self.workers:
                w.cancel()
            await asyncio.gather(*self.workers, return_exceptions=True)

        # Libero el pool de procesos (sin esperar procesos colgados)
        self.pool_procesos.shutdown(wait=False, cancel_futures=True)
        self._volcar()

    def _volcar(self):
        nombre = os.path.join(DIR_VOLCADOS, "estado_%d.json" % int(time.time()))
        with open(nombre, "w") as f:
            json.dump(list(self.registro.values()), f, indent=2, default=str)
        logging.info("Estado volcado a %s (%d tareas)", nombre, len(self.registro))
