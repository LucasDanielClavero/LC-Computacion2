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
COLA_MAXSIZE = int(os.environ.get("COLA_MAXSIZE", "100"))
DIR_VOLCADOS = "volcados"

ESTADOS_POSIBLES = ("pendiente", "ejecutando", "completada", "fallida", "cancelada")

# Centinela de apagado (clase 21): object() crea un objeto unico, distinto de
# cualquier dato que pueda llegar de afuera. Se compara con `is` (identidad),
# no con `==`. La clase advierte que None o "FIN" son peligrosos: podrian ser
# datos legitimos; con object() eso es imposible.
PASTILLA = object()


class ColaLlenaError(Exception):
    """Se levanta cuando la cola alcanzo su maxsize (backpressure)."""


class GestorTareas:
    def __init__(self):
        self.registro = {}       # id -> datos de la tarea (estado en memoria)
        self.cola = None         # asyncio.Queue: productores = endpoints, consumidores = workers
        self.workers = []        # las N corrutinas del pool
        self.en_curso = {}       # id -> asyncio.Task que esta ejecutando esa tarea
        self.pool_procesos = None  # ProcessPoolExecutor para las tareas CPU-bound
        self._contador = count(1)  # para generar ids: t1, t2, t3...
        self.aceptando = True    # False mientras se apaga: el POST responde 503

    # -----------------------------------------------------------
    # Arranque: se llama al levantar la API
    # -----------------------------------------------------------
    async def iniciar(self):
        os.makedirs(DIR_VOLCADOS, exist_ok=True)
        # maxsize = backpressure (clase 21): si la cola esta llena, la tarea
        # no entra y la API responde 503 en vez de aceptar trabajo que no
        # podriamos hacer. Sin limite, 10.000 tareas de golpe viven en memoria.
        self.cola = asyncio.Queue(maxsize=COLA_MAXSIZE)
        # pool de PROCESOS para el trabajo pesado de CPU (hashear).
        # En Linux usa fork, en macOS/Windows usa spawn (por eso el
        # arranque de la app esta protegido con if __name__ == "__main__").
        self.pool_procesos = ProcessPoolExecutor(max_workers=NUM_PROCESOS)
        # Caliento el pool: en 3.14 el default es forkserver y el primer uso
        # lanza los procesos, lo que demora del orden de ~1s si pasa con la
        # API ya atendiendo pedidos. Un mini-hash al arrancar deja los
        # procesos listos. Es la idea de la clase 21/22: el pool se arma una
        # vez al inicio y ya queda para toda la vida del servidor.
        # (Nota: hay que ir por run_in_executor: un concurrent.futures.Future
        # no es awaitable directo, solo el wrapper de asyncio lo es.)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(self.pool_procesos, hashear_bloqueante, "", 1)
        for i in range(NUM_WORKERS):
            self.workers.append(asyncio.create_task(self._worker(i)))
        logging.info("Gestor listo: %d workers, %d procesos para CPU-bound",
                     NUM_WORKERS, NUM_PROCESOS)

    # -----------------------------------------------------------
    # Encolar una tarea nueva (la llama el POST /tareas)
    # Devuelve inmediatamente: no espera a que termine.
    # -----------------------------------------------------------
    def encolar(self, tipo, params, timeout_s=None):
        if not self.aceptando:
            # Estamos apagando: no entro trabajo nuevo (consigna 4).
            raise RuntimeError("el servidor se esta apagando, no acepta tareas nuevas")
        self._validar_params(tipo, params)

        # Chequeo de la cola ANTES de crear nada. No hay await aca en el
        # medio, asi que la seccion critica es atomica por construccion:
        # en corrutinas el cambio de contexto solo ocurre en un await
        # (clase 20). Con await adentro habria que usar asyncio.Lock.
        if self.cola.qsize() >= COLA_MAXSIZE:
            raise ColaLlenaError(
                "cola llena: hay %d tareas pendientes disponibles y el max es "
                "de %d. Reintente mas tarde" % (self.cola.qsize(), COLA_MAXSIZE)
            )

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
            if not isinstance(params.get("en_event_loop", False), bool):
                raise ValueError("'en_event_loop' es opcional y tiene que ser booleano")
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
                if id_tarea is PASTILLA:
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
                    # Dos origen posibles, y hay que distinguirlos:
                    # 1) DELETE / apagado cancelo la SUB-TAREA (la unidad
                    #    cancelable es la tarea): el worker ESTA vivo y
                    #    debe solo marcar el estado y volver a su bucle.
                    # 2) Me cancelan A MI (el worker): el wait_for re-cancela
                    #    la sub-tarea tambien, con lo que mirar la sub-tarea
                    #    no distingue nada: absorber la cancelacion seria un
                    #    cancel sin efecto y el worker volveria al bucle sin
                    #    FINALIZAR nunca (lo tuve que comprobar en los tests).
                    # La discrimiacion oficial de 3.11+ es Task.cancelling():
                    # cuenta los cancel() dirigidos a ESTA task especifica.
                    if asyncio.current_task().cancelling() == 0:
                        tarea["estado"] = "cancelada"   # DELETE sobre la tarea
                    else:
                        tarea["estado"] = "cancelada"   # apagado: tambien queda cancelada
                        raise                            # asi el cancel tiene efecto
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
            if tarea["params"].get("en_event_loop"):
                # BUG INTENCIONAL, solo para mediciones (ver mediciones.py y
                # el README). Ejecutar CPU directo en una corrutina congela
                # el event loop entero: aca pasa exactamente eso, y el punto
                # de la medicion M2 es comparar contra el executor.
                # En uso normal NO pasar "en_event_loop": hashear va al pool.
                # Respeto la liquidazon: funcion pura al nivel del modulo,
                # porque ejecutarse directo o en un proceso la invoca igual.
                return hashear_bloqueante(
                    tarea["params"]["texto"], tarea["params"]["iteraciones"]
                )
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

        promedio = None
        if tiempos_completadas:
            promedio = round(sum(tiempos_completadas) / len(tiempos_completadas), 3)
        return {
            "totales_por_estado": totales,
            "tareas_totales": len(self.registro),
            "tiempo_promedio_ejecucion_s": promedio,
            "workers_ocupados": len(self.en_curso),
            "workers_totales": NUM_WORKERS,
            "tareas_en_cola": self.cola.qsize(),
            "aceptando_tareas": self.aceptando,
        }

    # -----------------------------------------------------------
    # Apagado ordenado. Lo llama uvicorn antes de cerrar.
    # 1) No acepto tareas nuevas (el POST responde 503)
    # 2) Las pendientes NO arrancan: quedan cancelada en el registro y
    #    el worker las saltea al sacarlas de la cola. (La pastilla va
    #    ULTIMA en la cola (FIFO): si las pendientes no se marcaran, los
    #    workers las ejecutarian todas antes de llegar a la pastilla, y
    #    el apagado se estiraria indefinidamente.)
    # 3) Espero, con limite, a que la cola se procese: join() devuelve
    #    cuando a todo item le correspondio su task_done() (el worker
    #    lo hace en el finally), incluida la tarea en curso de cada worker.
    # 4) Si alguien no termino a tiempo, cancelo SOLO la sub-tarea.
    #    NUNCA cancelo el worker: el worker atraparia su propia
    #    CancelledError (el except que marca 'cancelada'), volveria al
    #    bucle como si nada, y el cancel no tendria efecto.
    # 5) Dreno lo que quedo en la cola, mando las pastillas y volteo
    #    el estado a volcados/estado_<timestamp>.json
    # -----------------------------------------------------------
    async def apagar(self):
        self.aceptando = False
        logging.info("Apagado ordenado: no acepto mas tareas")

        # (2) Las pendientes quedan canceladas y no se ejecutan.
        for tarea in self.registro.values():
            if tarea["estado"] == "pendiente":
                tarea["estado"] = "cancelada"
                tarea["error"] = "cancelada durante el apagado"
                tarea["termino"] = time.time()

        # (3) Espero con limite a que se procese lo que corre
        try:
            await asyncio.wait_for(self.cola.join(), timeout=LIMITE_APAGADO)
            logging.info("Las tareas en curso terminaron dentro del limite")
        except asyncio.TimeoutError:
            logging.warning(
                "No terminaron en %.0fs: cancelo las tareas en curso",
                LIMITE_APAGADO,
            )
            # Cancelo solo las SUB-tareas (la unidad cancelable es la tarea),
            # nunca el worker, y espero a que procesen la cancelacion.
            for id_tarea, futura in list(self.en_curso.items()):
                self.registro[id_tarea]["estado"] = "cancelada"
                futura.cancel()
            en_curso = list(self.en_curso.values())
            if en_curso:
                await asyncio.gather(*en_curso, return_exceptions=True)

        # Barrido de la cola: lo que quedo ahi son ids de tareas canceladas
        # que nadie consumo todavia. Los saco con get_nowait, con su
        # task_done(), para que las pastillas entren seguro despues.
        drenadas = 0
        while not self.cola.empty():
            try:
                self.cola.get_nowait()
                self.cola.task_done()
                drenadas += 1
            except asyncio.QueueEmpty:
                break
        if drenadas:
            logging.info("Cola drenada al apagar: %d ids restantes", drenadas)

        # (5) Cola vacia: las pastillas entran al toque con put_nowait y los
        # workers salen del bucle sin que nadie los cancele.
        for _ in self.workers:
            self.cola.put_nowait(PASTILLA)
        await asyncio.wait_for(asyncio.gather(*self.workers), timeout=LIMITE_APAGADO)

        # Libero el pool de procesos (sin esperar procesos colgados) y volcar
        self.pool_procesos.shutdown(wait=False, cancel_futures=True)
        self._volcar()

    def _volcar(self):
        nombre = os.path.join(DIR_VOLCADOS, "estado_%d.json" % int(time.time()))
        with open(nombre, "w") as f:
            json.dump(list(self.registro.values()), f, indent=2, default=str)
        logging.info("Estado volcado a %s (%d tareas)", nombre, len(self.registro))
