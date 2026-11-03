# TP2 — Plataforma de Tareas Distribuidas

Computación II — Universidad de Mendoza — 2026

Un servidor HTTP al que se le encargan tareas. Las acepta al instante, las
ejecuta en segundo plano de forma concurrente y permite consultar el estado y
el resultado de cada una. El historial de versiones del TP está en
[documentacion/CHANGELOG.md](documentacion/CHANGELOG.md).

## 1) Descripción y uso

### Tipos de tarea

La API acepta tres tipos:

- **`esperar`**: duerme N segundos y listo. Es la ideal para probar: tarda lo
  que vos le pidas y se la alcanza a ver pasar por los estados.
- **`descargar`**: baja un grupo de URLs en paralelo (trabajo de red).
- **`hashear`**: calcula un SHA-256 iterado (trabajo pesado de CPU) y lo corre
  en otro proceso para no frenar el servidor.

### Estructura del proyecto

```
tp2/
├── src/                  # el código
│   ├── main.py           # punto de entrada: levanta uvicorn con la app
│   ├── api.py            # los 5 endpoints HTTP
│   ├── gestor.py         # la cola, los workers, timeouts, cancelación y volcado
│   └── tareas.py         # las 3 tareas: esperar, descargar, hashear
├── tests/
│   └── test_api.py       # pruebas automatizadas (pytest)
├── scripts/
│   └── mediciones.py     # script de las 3 mediciones de la consigna
├── documentacion/        # material del TP que no es código
│   ├── comandos.md       # todos los comandos para probar la API, con su explicación
│   └── CHANGELOG.md      # versiones del TP
├── README.md             # este informe
├── volcados/             # los JSON del estado que se escriben al apagar
├── conftest.py           # fixture compartida de los tests
├── pytest.ini            # configuración de pytest
├── docker-compose.yml    # cómo se levanta el servicio
├── Dockerfile            # la imagen del contenedor
└── requirements.txt      # dependencias
```

### Cómo arrancar

Requisito: tener Docker con el plugin `docker compose`. No hace falta
instalar Python ni nada: todo corre dentro del contenedor.

```bash
# 1. entrar a la carpeta del TP y levantar el servicio
cd tp2
docker compose up --build

# 2. cuando termine de arrancar, la API queda en http://localhost:8000
#    (y la documentación interactiva en el navegador: http://localhost:8000/docs)

# 3. probar los comandos de abajo desde otra terminal

# 4. para apagar: Ctrl+C en la terminal donde corre
#    (hace el apagado ordenado y escribe el estado en volcados/)
```

### Comandos y qué hace cada uno

Los pedidos que entiende la API se prueban con `curl`. Tengo toda la lista
junta — cada comando con su explicación de qué hace y qué responde — en
[documentacion/comandos.md](documentacion/comandos.md).

Los dos que muestran la idea general del TP: crear una tarea (el POST
responde al instante, con el id) y mirar cómo avanza:

```bash
curl -X POST http://localhost:8000/tareas -H 'Content-Type: application/json' \
  -d '{"tipo": "esperar", "params": {"segundos": 10}}'
curl http://localhost:8000/tareas/t1
```

### Correr los tests

Además de probar a mano con los comandos de arriba, la app tiene una suite
automatizada: 11 pruebas con `pytest` que corren contra la app real (mismo
ciclo de vida, mismos workers), sin levantar el contenedor y sin tocar la red.

```bash
cd tp2
python3 -m venv .venv             # entorno propio con las dependencias
source .venv/bin/activate
pip install -r requirements.txt   # pytest, pytest-asyncio y httpx están acá
python -m pytest tests/ -v
```

---

## 2) Diagrama de arquitectura

```
   Cliente HTTP
        │
        ▼
┌───────────────────────────┐
│ uvicorn                   │  el event loop vive acá
│ (servidor ASGI)           │  (socket, protocolo HTTP, epoll)
└────────────┬──────────────┘
             ▼
┌───────────────────────────┐
│ api.py  (FastAPI)         │  los 5 endpoints
│ POST /tareas              │──── tarea nueva ────┐
│ GET /tareas               │                     ▼
│ GET /tareas/{id}          │            ┌──────────────────────┐
│ DELETE /tareas/{id}       │            │ asyncio.Queue        │
│ GET /estadisticas         │            │ maxsize=100          │
└────────────▲──────────────┘            │ (backpressure)       │
             │                           └──────────┬───────────┘
   estado/resultado                                │
   (vuelven del registro)                          ▼
             │                           ┌──────────────────────┐
             └───────────────────────────│ gestor.py            │
                                         │ 3 workers (corrutinas│
                                         │ del mismo event loop)│
                                         │ registro en memoria  │
                                         └───┬──────────────┬───┘
                                   I/O-bound │          CPU-bound │
                                             ▼                  ▼
                                    await directo        run_in_executor
                                    (esperar,            (hashear: sale a
                                     descargar)           otro proceso)
```

Este es el esquema de las tres capas: **uvicorn tiene el event loop** (el
socket, el protocolo HTTP y por debajo el epoll de la clase 17), **FastAPI es
la aplicación** (rutas y respuestas) y encima va lo mío: cola + workers +
executor.

**Flujo de una tarea:**

1. El `POST /tareas` valida tipo y params, y chequea la cola. Si está llena
   responde `503` (backpressure): mejor rechazar que aceptar trabajo que va a
   quedar eternamente en espera.
2. Si acepta, responde al instante `201` con `{"id": "t1", "estado":
   "pendiente"}` — se espera cero a que la tarea termine.
3. Un worker saca el id de la cola, la marca `ejecutando` y la corre como
   **sub-tarea propia** (`create_task`) envuelta en `wait_for(timeout)`. Acá
   se apoyan el timeout y la cancelación.
4. Según el tipo: `esperar` hace `await asyncio.sleep()` (I/O simulado),
   `descargar` baja todas las URLs con `gather` + `ClientSession`, y `hashear`
   se va al `ProcessPoolExecutor` (sí, otro proceso) para que el cálculo no
   frene el loop.
5. Estado final: `completada`, `fallida` (con motivo o por timeout vencido) o
   `cancelada`.
6. Al apagar ordenadamente, todo el registro se vuelca a
   `volcados/estado_<timestamp>.json`.

---

## 3) Decisiones de diseño

### ¿Por qué `asyncio.Queue` y no `queue.Queue`?

Porque en este sistema la cola se comparte entre los endpoints y los workers,
y todos viven en el mismo event loop. Una `queue.Queue` es para threads: si
un worker hiciera ahí un `get()` con la cola vacía, se bloquearía el hilo
completo — el server entero, no solo ese worker. Con `asyncio.Queue` la
espera es un `await`: queda suspendida solo esa corrutina y el loop sigue con
todo lo demás. Y como el scheduling es cooperativo (el código no se ve
interrumpido entre un `await` y otro, clase 20), ni la cola ni el registro
necesitan `Lock` para no corromperse.

### ¿Cómo evitás que una tarea CPU-bound congele la API?

El cálculo de `hashear` no corre en el event loop: sale por
`loop.run_in_executor(ProcessPoolExecutor, ...)` a otro proceso, y los
procesos son paralelismo de verdad (los threads no lo dan, por el GIL).
Mientras se están calculando los hashes, el server sigue atiendo pedidos sin
problema. En números (medición **M2**): con el hash corriendo dentro del loop
(existe el flag `en_event_loop`, un bug a propósito), un GET tardó
**3066 ms**; con executor, **7 ms** en el peor caso.

### ¿Cómo implementaste la cancelación, y qué pasa con los recursos a medio usar?

Tres casos:

- **Pendiente:** la marco `cancelada` en el registro. De una `asyncio.Queue`
  no se puede sacar algo del medio (es física de la cola); el worker la lee
  al sacarla y la saltea. El registro en memoria es la única fuente de
  verdad de los estados.
- **En ejecución:** de la tarea se cancela su sub-tarea (`cancel()`), que
  inyecta una `CancelledError` en su próximo `await` (clase 20). El worker la
  recibe, marca `cancelada` con motivo, libera el slot y sigue con su ciclo.
  La unidad cancelable es la tarea, nunca el worker.
- **Al apagar:** no entra trabajo nuevo, las pendientes quedan `cancelada` y
  no se suben; se alcanza a esperar (con límite) a las en curso; si el límite
  vence, se las cancela; y al final un volcado del registro a JSON.

Con los recursos no hay limpieza especial, la que sale sola: la
`ClientSession` está dentro de un `async with` y los `task_done` van al
`finally`, así que la liberación funciona aunque la corrutina salga por
cancelación (clase 20). Un caso queda por fuera: un `DELETE` no interrumpe un
`hashear` ya en ejecución dentro del executor — el proceso no tiene `await`
donde inyectar la excepción (limitación §6).

### ¿Qué pasa si un worker lanza una excepción no capturada?

Puede pasar de dos niveles distintos:

- **La tarea lanza una excepción.** El worker la atrapa (espera a la
  sub-tarea dentro de un `try/except Exception`), la marca `fallida` con el
  mensaje en el campo `error`, y **sigue con su ciclo** — el servicio no se
  entera.
- **El bucle del worker lanza una excepción** (un bug mío). Ese worker muere,
  pero el resto del pool sigue: queda con N-1 workers. La tarea que tenía en
  curso queda enganchada en `ejecutando` para siempre — es una limitación
  conocida (§6).

---

## 4) Mediciones

Las tres obligatorias de la consigna, tomadas con `scripts/mediciones.py`
contra el server levantado (`docker compose up`). El cliente de medición y
Docker corren en esta máquina: Linux Mint 22.3, CPU 12 núcleos, 15 GB de
RAM. El server corre adentro del contenedor, con la imagen `python:3.11-slim`
(Python 3.11.18 sobre Debian 13); el contenedor no tiene límites de CPU, así
que los cálculos usan los núcleos reales de la máquina. Reproducibles con
`python3 scripts/mediciones.py` en otra terminal.

### M1 — Concurrencia I/O: 20 descargas secuenciales vs 20 concurrentes

Descargar las mismas 20 URLs de dos formas: 20 tareas de a una URL
(secuencial) o una sola tarea con las 20 (concurrente).

Secuencial: (20 tareas, 1 URL cada una) | 4.718 s |
Concurrente: (1 tarea con las 20 URLs) |0.748 s|

En paralelo demora mucho menos que en serie,
porque una descarga es casi puro esperar la red (~0.23 s por URL) y las
esperas se pueden encimar: los 20 pedidos salen al mismo tiempo y el total
queda cerca de lo que tarda la más lenta, no de la suma de todas.

### M2 — El event loop bloqueado: CPU en el loop vs en el executor

Corriendo un hash pesado (~3 segundos), mando un `GET /estadisticas` cada
50 ms y mido el peor atraso:

| Modo | GETs recibidos en ese lapso | Peor atraso |
|---|---|---|
| CPU adentro del loop (`en_event_loop: true`) | **1** | **3066 ms** |
| CPU afuera, en el executor (modo normal) | 57 | **7.3 ms** |

Reflexión: con el cálculo corriendo adentro del loop, el server queda
congelado los 3 segundos que dura el hash — hasta una request alcanzó a
pasar, y tardó lo mismo que el cálculo. Con el executor, el server sigue
respondiendo con latencia normal, porque el cálculo corre en otro proceso y
el loop queda libre. La regla que deja en claro: nada de cálculo pesado en
el event loop. 

### M3 — Techo del pool

Mandar N tareas de 1 s todas de golpe (3 workers) y medir cuánto tarda el
grupo entero en terminar:

| N | Tiempo total | Techo teórico `ceil(N/3)×1s` | Peor atraso (espera en cola) |
|---|---|---|---|
| 1 | 1.03 s | 0.33 s | 2 ms |
| 3 | 1.06 s | 1.00 s | 2 ms |
| 6 | 1.99 s | 2.00 s | 983 ms |
| 12 | 4.01 s | 4.00 s | 2.948 s |
| 24 | 7.88 s | 8.00 s | 6.875 s |
| 48 | 15.69 s | 16.00 s | 14.685 s |
| 96 | 31.46 s | 32.00 s | 30.397 s |

Reflexión: el tiempo total se comporta tal cual el techo de 3 workers,
dando que seria mas o menos 3 tareas por segundo, sin importar cuánto suba
la cola. Lo único que crece es la espera del último en llegar (con N=96,
~30 s): la cola no acelera nada, solo absorbe los picos — y cuando la cola
se llena (100, `COLA_MAXSIZE`), el POST responde 503.

---

## 5) Conceptos del curso aplicados

Voy por orden, de la clase 17 a la 22:

### Clase 17 — I/O multiplexing

El event loop que vive dentro de uvicorn: espera muchos sockets a la vez, y
eso es lo que permite que un solo hilo atienda todos los pedidos sin
bloquearse. Toda mi API corre encima de eso.

### Clase 18 — De `yield` a asyncio

Las corrutinas y los `await`. Cada `await` pausa la función que lo ejecuta y
le devuelve el control al loop, que pasa a otra cosa. Es la mecánica que usa
todo el sistema: los endpoints atienden pedidos sin pisar a los workers, y
`esperar` simplemente hace `await asyncio.sleep()` — espera sin consumir
CPU mientras tanto.

### Clase 19 — HTTP + FastAPI

La API entera: los 5 endpoints con sus modelos de entrada validados
(Pydantic), uvicorn como servidor, y la página `/docs` que FastAPI genera
solo de leer las anotaciones. Todos los endpoints son `async`, así que se
quedan adentro del loop y no agregan threads extra.

### Clase 20 — Asyncio en red

Con esta clase hago casi todo lo de red y de cancelación:

- `descargar` usa `gather` + `ClientSession`: todas las URLs al mismo
  tiempo, con timeout por URL y la sesión de conexiones compartida.
- Todo tiene timeout: cada tarea corre envuelta en `wait_for(timeout)`, así
  que ninguna puede colgar el servidor para siempre.
- La cancelación: el `DELETE` corta la sub-tarea con `Task.cancel()`, que
  entra en el próximo `await`, y la tarea queda `cancelada`. Al cerrarse, la
  `ClientSession` se libera sola por el `async with`, aunque la corrutina
  salga cancelada — la limpieza sale sola, sin código especial.
- No instalo signal handlers propios: uvicorn ya corta los pedidos nuevos al
  recibir la señal, y después corre mi apagado (mismo resultado, sin
  duplicar el trabajo).

### Clase 21 — Asyncio avanzado

El corazón del TP:

- La cola `asyncio.Queue` + 3 workers: el patrón productor-consumidor, con
  `task_done()` en el `finally` para que el contador interno de la cola baje
  siempre (sino `join()` espera eternamente).
- Backpressure: la cola tiene `maxsize=100`; si llega a llenarse, el POST
  responde 503 en vez de seguir tomando tareas.
- El apagado ordenado: los workers son bucles infinitos, así que usan una
  *pastilla* (un `object()` como centinela) para salir; al apagar se marcan
  las pendientes como canceladas, se espera con límite a las en curso y si
  el límite vence, se cancelan.

### Clase 22 — concurrent.futures

El `hashear` sale del event loop con `run_in_executor(ProcessPoolExecutor)`:
el cálculo corre en otro proceso (los threads no dan paralelismo por el
GIL) y el server sigue respondiendo. La función es top-level porque los
pasajes entre procesos viajan serializados (pickle), y el pool se crea una
sola vez al arrancar, no por pedido.

---

## 6) Limitaciones conocidas

- **El estado no se recupera al arrancar.** Las tareas viven en memoria; al
  apagar se escribe el volcado JSON con todos los estados, pero es
  informativo (se reporta en el log, no se re-encola nada). Reponer el
  estado pide decidir qué pasa con las que estaban ejecutando en el momento
  del apagado, y sin base de datos esa pregunta no tiene respuesta clara.
- **Un `DELETE` no interrumpe un `hashear` ya en marcha.** El corte funciona
  inyectando la excepción en un `await`, y el cálculo que corre dentro del
  proceso del executor no tiene ningún `await`. La tarea queda marcada como
  a cancelar hasta que el hash termina; para cortarlo de verdad necesitaría
  matar procesos a mano, con los riesgos de esa vía.
- **Si un worker muere, su tarea queda trabada en `ejecutando`.** Solo pasa
  si el bug está dentro del bucle del worker (no en la tarea): quién tenía
  que marcarla era justamente él. El resto del pool sigue funcionando igual
  — es el otro lado de que cada worker sea una corrutina independiente.
- **Corre con un solo proceso de uvicorn.** Con `--workers N` serían N
  procesos con N event loops distintos, y el registro de tareas en memoria
  no se comparte entre procesos. Sin base de datos, el diseño coherente es
  este.

---

## 7) Lo que aprendiste

Lo que más me dejó este TP fueron las mediciones, porque me mostraron en
números lo que la teoría decía. Me quedó claro que en paralelo demora menos
que en serie (M1: 6.31× en las descargas), porque las esperas se enciman en
vez de sumarse. También que el tiempo que tarda cada worker casi no cambia
el tiempo de respuesta del server: los picos los absorbe la cola y lo único
que crece es la espera del último en llegar. Y la regla fuerte: nada de
cálculo pesado en el event loop — con el hash adentro el server quedaba
congelado 3 segundos; con el executor, 7 milisegundos.

El bug del que más me acuerdo es el del apagado: cerrábamos el server y, con
la cola cargada, quedaban tareas pendientes que los workers seguían
ejecutando antes de salir. Ahí aprendí que un bucle infinito necesita un
modo de salir prolijo (la "pastilla" que se les manda a los workers) y que
el apagado tiene que tener una espera con límite, si no puede estirarse sin
fin.

Si arrancara de cero, uso `run_in_executor` desde el primer día: no correría
ningún cálculo en el loop "provisionalmente", ni para probar algo rápido,
porque la trampa de bloquear el server cuesta carísimo y no se nota hasta
que se mide. Y pondría los tests desde el principio, no al final: los sumé
cuando el TP ya estaba casi listo, y fue la suite de tests la que encontró
el bug del apagado — el problema estaba ahí hace semanas y lo destapó un
test, no el uso manual.
