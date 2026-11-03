# TP2 — Plataforma de Tareas Distribuidas

**Computación II — Universidad de Mendoza — 2026**

Un servicio HTTP al que se le encargan trabajos, los ejecuta de forma
concurrente y permite consultar su estado y resultado.

**Estado actual:** funcional para todo lo obligatorio de la consigna, con las
tres mediciones medidas en esta máquina. El historial de versiones está en
[CHANGELOG.md](CHANGELOG.md).

---

## 1. Descripción y uso

### Arquitectura

```
   Cliente HTTP
        |
        v
   uvicorn  (servidor ASGI: socket, protocolo HTTP y el event loop)
        |
   ┌────────────────────┐        ┌───────────────────────────┐
   │  API (FastAPI)     │───────>│ asyncio.Queue             │
   │  POST /tareas      │        │ maxsize=100 (backpressure)│
   │  GET  /tareas      │        └─────────┬─────────────────┘
   │  GET  /tareas/{id} │                  |
   │  DELETE /tareas/{id}│        ┌─────────▼─────────────────┐
   │  GET /estadisticas │        │ Pool de N workers         │
   └────────────────────┘        │ (corrutinas del event loop)│
        ^                        └──┬──────────────────────┬─┘
        |                           I/O-bound             CPU-bound
    estado/resultado             await directo          run_in_executor
    (registro en memoria)      (descargar, esperar)     (hashear → proceso)
```

Las tres capas de la clase 19 están presentes: **uvicorn tiene el event
loop** (el socket, el protocolo HTTP, y por debajo el `selectors`/`epoll` de
la clase 17), **FastAPI es la aplicación** (rutas, validación, respuestas).
Encima de eso agregamos la arquitectura del TP: cola + workers + executor.

**Flujo de una tarea:**

1. El `POST /tareas` valida el tipo y los params, y chequea que la cola no
   esté llena. Si lo está, responde **503** (backpressure, clase 21) en vez
   de aceptar trabajo que no va a poder hacer.
2. Responde **inmediatamente** `201 Created` con
   `{"id": "tN", "estado": "pendiente"}`: espera
   cero a que la tarea termine.
3. Un worker saca el id de la cola, marca la tarea como `ejecutando`, y la
   corre como **sub-tarea propia** (`asyncio.create_task`) envuelta en
   `asyncio.wait_for(timeout)`. Ahí se apoyan el timeout y la cancelación
   (ambos son mecánica de la clase 20).
4. La sub-tarea, según el tipo:
   - `esperar`: `await asyncio.sleep()` — cede el control, I/O simulado.
   - `descargar`: `asyncio.gather` + `aiohttp.ClientSession` — todas las
     URLs al mismo tiempo, con timeout por URL.
   - `hashear`: `loop.run_in_executor(ProcessPoolExecutor)` — el SHA-256
     iterado corre en otro proceso y el event loop queda libre.
5. Estado final: `completada`, `fallida` (con motivo), `cancelada`, o
   `fallida` por timeout vencido.
6. El registro completo vive en memoria. Al apagar ordenadamente se vuelca a
   `volcados/estado_<timestamp>.json`, y al arrancar los volcados previos se
   reportan por log.

### Ejecutar

```bash
docker compose up --build     # la API queda en http://localhost:8000
```

La documentación interactiva generada automáticamente está en
`http://localhost:8000/docs` (FastAPI la produce de las anotaciones de tipo y
los modelos Pydantic — clase 19).

### Estructura del código

| Archivo | Contiene |
|---|---|
| `src/api.py` | Los 5 endpoints y el ciclo de vida (lifespan) |
| `src/gestor.py` | La cola, el pool de workers, timeout, cancelación, volcado |
| `src/tareas.py` | Las 3 tareas `esperar`, `descargar`, `hashear` |
| `src/main.py` | Entrada: `uvicorn.run` con la guarda `__main__` |
| `scripts/mediciones.py` | Las 3 mediciones contra una instancia arriba |
| `tests/test_api.py` | 11 pruebas automatizadas (pytest-asyncio), vía ASGI sin red |

#### Pruebas automatizadas (bonus de la consigna)

Además de los `curl` y `scripts/mediciones.py`, la suite con
`pytest-asyncio` corre contra la app de verdad — mismo `lifespan`, mismo
gestor, workers incluidos, sin tocar la red (via `httpx.ASGITransport`):

```bash
python -m pytest tests/ -v
```

Cubren: POST inmediato (201), ciclo completo con filtro y estadísticas,
`hashear` por executor, validaciones (400) y 404, timeout → `fallida`,
**cancelación en ejecución** (inmediata, y la API sigue viva), cancelación
de `pendiente` que nunca arranca, 409 sobre terminadas, backpressure
(cola llena → 503), excepción de tarea → `fallida` y el worker sigue vivo,
y **apagado acotado con cola cargada** (el caso difícil del §2, que además
encontró y corrigió el detalle fino del cancel al worker).

### Ejemplos de `curl`

```bash
# I/O simulado: la ideal para ver estados en vivo, timeouts y cancelaciones
curl -X POST http://localhost:8000/tareas \
  -H 'Content-Type: application/json' \
  -d '{"tipo": "esperar", "params": {"segundos": 20}}'

# descarga concurrente: las urls se piden todas al mismo tiempo
curl -X POST http://localhost:8000/tareas \
  -H 'Content-Type: application/json' \
  -d '{"tipo": "descargar", "params": {"urls": ["https://example.com", "https://www.python.org"]}}'

# hash pesado (CPU-bound): corre en otro proceso, la API sigue respondiendo
curl -X POST http://localhost:8000/tareas \
  -H 'Content-Type: application/json' \
  -d '{"tipo": "hashear", "params": {"texto": "hola", "iteraciones": 3000000}}'

# el mismo hash corrido DIRECTO en el event loop: bug a propósito, para la medición M2
curl -X POST http://localhost:8000/tareas \
  -H 'Content-Type: application/json' \
  -d '{"tipo": "hashear", "params": {"texto": "hola", "iteraciones": 3000000, "en_event_loop": true}}'

# listar todo (o con filtro: pendiente|ejecutando|completada|fallida|cancelada)
curl http://localhost:8000/tareas
curl "http://localhost:8000/tareas?estado=ejecutando"

# estado y resultado de una tarea
curl http://localhost:8000/tareas/t1

# cancelar (igual sirve para pendiente que para en ejecucion; una tarea
# ya terminada responde 409)
curl -X DELETE http://localhost:8000/tareas/t1

# estadisticas (incluye workers ocupados y tareas en cola)
curl http://localhost:8000/estadisticas
```

Configuración por variables de entorno (en `docker-compose.yml`):
`NUM_WORKERS` (3), `NUM_PROCESOS` (2), `TIMEOUT_DEFAULT` (60),
`COLA_MAXSIZE` (100) y `LIMITE_APAGADO` (10).

---

## 2. Decisiones de diseño, argumentadas

### ¿Por qué `asyncio.Queue` y no `queue.Queue`?

Porque conecta productores (los endpoints) y consumidores (los workers),
igual que el patrón productor-consumidor de la clase 11 — el mismo _patrón_,
pero con corrutinas en lugar de threads — y las dos colas viven en mundos de
scheduling distintos:

1. **`queue.Queue` se piensa para threads.** Sus esperas usan locks y
   variables de condición de `threading`. Si un worker hiciera `cola.get()`
   sobre una `queue.Queue` vacía, el hilo entero — el único hilo del event
   loop — se bloquearía hasta que llegara algo: los endpoints muertos, si los
   otros workers, muertos. Con `asyncio.Queue`, el get vacío es un `await`:
   suspende *solo esa corrutina* y el loop sigue con lo demás.
2. **En el loop no hace falta Lock, y la cola tampoco lo necesita.** La
   sección crítica entre endpoints y workers (put, get, task_done, la
   actualización del registro) es atómica por construcción: con corrutinas el
   cambio de contexto solo ocurre en un `await` (clase 20), y entre un `await`
   y otro nada interrumpe el código. La "seguridad" que en threads
   compramos con locks en el caso async la da el scheduling cooperativo.

Es la respuesta a la pregunta de la corrección: *el pool de workers consume
de una `asyncio.Queue` compartida — es el mismo patrón productor-consumidor
de la clase 11, pero con corrutinas: no hace falta lock porque el event loop
no interrumpe entre `await`s.*

Complemento de diseño: la cola tiene `maxsize` y el endpoint rechaza con 503
cuando está llena. Es la recomendación de la clase 21 para un servidor que
toma pedidos de afuera: sin límite, una avalancha de tareas vive en memoria;
con límite, el servidor(manifesta el entrenamiento) en vez de aceptar trabajo
que no podrá hacer.

### ¿Y por qué un solo proceso de uvicorn?

Porque con `uvicorn --workers N` son N procesos con N event loops distintos y
**la memoria no se comparte entre ellos** (clase 19): mi registro de tareas
es un dict en un proceso, invisible para los otros. La consigna pide el
estado en memoria — sin base de datos — así que el trade-off coherente es un
solo proceso de uvicorn, y el paralelismo real lo aporta el
`ProcessPoolExecutor` interno (que sí escala los cores con los procesos
hijos).

### ¿Cómo evitás que una tarea CPU-bound congele la API?

La CPU no puede correr en el event loop: la corrutina que lo haga nunca va a
ceder el control, y el loop entero queda congelado — es la regla de la clase
17 ("nada lento en el hilo del bucle") repetida en la 18 y **medida en la
21** (`hash de 5s directo en la corrutina: 4807 ms de atraso del loop;
con executor: 6.3 ms` — nuestra medición M2 da un resultado equivalente:
3066 ms vs 7.3 ms).

Por eso `hashear` se ejecuta con
`loop.run_in_executor(pool_procesos, hashear_bloqueante, texto, iteraciones)`.
Detalles de la elección:

- **Procesos y no threads:** el GIL hace que varios threads de cálculo se
  turnen el bytecode — la clase 21 lo mide con 4 hashes: 11.53 s threads
  contra 3.42 s procesos. Con procesos hay paralelismo real.
- **La función es top-level** (`hashear_bloqueante` en `tareas.py`): los
  argumentos y el resultado viajan pickleados (clase 22), y las lambdas no se
  picklean.
- **El pool se crea una vez**, al arrancar la app con `lifespan` (clase 22:
  crear un pool de procesos cuesta ~10 ms; si se creara por pedido, sería un
  costo extra constante), y se **calienta** con un mini-hash para que el
  arranque del `forkserver` (el default de multiprocessing en Linux desde
  Python 3.14) no le pague al primer pedido un atraso de ~1 s — verificado
  en la medición M2 (el primer vuelo con executor daba un peor atraso
  de ~1 s hasta que agregamos el calentamiento).
- **La guarda `if __name__ == "__main__"`** en `main.py`: en macOS/Windows el
  pool arranca con `spawn` y re-importa el módulo; sin la guarda, el programa
  entra en bucle de reimportación (lo marca la consigna).

La prueba es la **medición M2** de la siguiente sección: 3066 ms vs 7.3 ms.

### ¿Cómo implementaste la cancelación, y qué pasa con los recursos?

Tres casos:

**Pendiente:** no existen operaciones para eliminar de una `asyncio.Queue` algo
del medio, así que la tarea *se marca* `cancelada` en el registro: cuando un
worker la saque, ve el estado y la saltee — la cola no es fuente de verdad de
estados, el registro es, y así solo se lee un campo para decidir.

**En ejecución:** el worker la corre con una sub-tarea separada
(`futura = asyncio.create_task(self._correr_tarea(tarea))`) y guarda la
referencia en `self.en_curso`. `DELETE` sobre una tarea en ejecución hace
`en_curso[id].cancel()`, que **inyecta `CancelledError` en el próximo
`await`** de la tarea (clase 20). La sub-tarea muere, y el worker está
esperarla con `wait_for`: recibiendo la cancelación, marca la tarea como
`cancelada` y libera el slot del `en_curso`. La unidad cancelable es *la
tarea*, no el worker: el worker sigue su bucle inmediatamente con la próxima.

**Apagando el servidor:** el orden es importante y lo hicimos así:

1. `aceptando = False`: el gestor no entra trabajo nuevo (el `POST` responde
   503). Es lo primero que hace `apagar()`.
2. **Las pendientes no arrancan.** Se marcan `cancelada` (con motivo) y el
   worker las saltea al sacarlas de la cola (ese salteo ya existía). Acá está
   la razón más fina: la pastilla va al **final** de la cola (FIFO) — si las
   pendientes no se marcaran, los workers las ejecutarían todas antes de
   llegar a la pastilla y el apagado podría estirarse indefinidamente.
3. Esperamos, con límite (`LIMITE_APAGADO`, 10 s), a que la cola se procese
   con `cola.join()`: el contador interno de la cola incluye también las
   tareas en curso (el worker hace su `task_done` al final), así que join()
   exactamente espera "las que están en curso" — lo que pide la consigna.
4. Si fuera del límite, se cancelan **solo las sub-tareas** (`en_curso`), con
   `futura.cancel()`. Nunca al worker: el worker está preparado para atrapar
   la `CancelledError` de su sub-tarea (es el mecanismo del DELETE) y si la
   absorbiera también la suya, el cancel quedaría *sin efecto* — detectado y
   corrido en los tests; el discriminador es `Task.cancelling()` (3.11+),
   que cuenta los `cancel()` dirigidos a cada task.
5. Con la cola vacía, una pastilla por worker con `put_nowait` — salen al
   instante — se libera el pool de procesos (`shutdown(wait=False)`) y se
   volca el estado a JSON.

**¿Y los recursos a medio usar?** La limpieza no depende de *cómo* salió la
corrutina, sino de los contextos con los que está armada: la
`aiohttp.ClientSession` está dentro de un `async with` (y el timeout por URL
es de aiohttp), así que la sesión se cierra sola cuando la corrutina sale —
aunque salga por `CancelledError`, porque Python garantiza que los `finally`
y los context managers se ejecutan igual (clase 20: limpieza con `finally`,
relanzando la cancelación). El `task_done()` del worker también va en el
`finally`, para que el contador interno de la cola baje siempre.

⚠ **Caso límite que queda: `cancel()` no interrumpe un cálculo ya en curso en
el executor.** El mecanismo de la clase 20 es inyectar la excepción en un
`await` — pero el `hashear` corriendo dentro del proceso del pool no tiene
ningún `await`: no hay punto donde inyectar. La misma regla que dice
`concurrent.futures`: el `cancel()` solo funciona si la tarea no arrancó
(clase 22). Consecuencia práctica: un `DELETE` sobre un `hashear` en curso
no interrumpe al proceso; el estado queda "pendiente de cancelar" hasta que
el proceso termine. Es una limitación aceptada (§5).

→ La cancelación de `descargar` a mitad de una descarga real quedó probada
con curl en la **sección 3, "Robustez"**.

### ¿Qué pasa si un worker lanza una excepción no capturada?

Vale distinguir dos niveles — y hay prueba real de esto:

**1. La tarea explota** (la sub-tarea que el worker está esperando). El
worker la consume con `wait_for` dentro de un `try/except Exception`: la
excepción de la sub-tarea se convierte en estado `fallida`, con el mensaje
en el campo `error`, y el worker sigue con su bucle. El servicio no se ve
afectado. Es el caso común de las URLs malas en `descargar`:
`_descargar_una` atrapa el error de cada URL y devuelve el detalle de esa
URL dentro del resultado (con `codigo: null` y el `error`), y la tarea queda
`completada`. Un error más general (por ejemplo, params que llegaron bien al
POST pero no al ejecutarse, o un objeto no picklable en el executor) corta
la sub-tarea entera: el tipo, en el nivel de la tarea, convierte a `fallida`.

**2. El *worker mismo* explota** (un bug en nuestro bucle). Ese error mata la
corrutina de ese worker, pero el resto del pool sigue y el servicio queda con
N-1 workers; uvicorn reporta la excepción en el log (asyncio la printea como
"Task exception was never retrieved" cuando destruye la Task que nadie
esperó). El efecto es fino: la tarea que ese worker tenía en curso queda
parada en `ejecutando` para siempre — la anotamos como limitación conocida
El efecto fino es que la tarea que ese worker tenía en curso queda en
`ejecutando` para siempre — lo anotamos como limitación conocida (§5). Lo
bueno del aislamiento es que los demás workers ni se enteran: el patrón de
la clase 21 (workers como corrutinas independientes) trae esa granularidad.

---

## 3. Mediciones

Todas fueron tomadas con `scripts/mediciones.py` contra nuestra instancia de
la API, en localhost:8000, en la máquina de desarrollo (Ubuntu 24.04, Docker
con imagen `python:3.11-slim`, CPU 4 núcleos). Se puede reproducir con solo
`python3 scripts/mediciones.py`.

### M1 — Concurrencia I/O: 20 descargas secuenciales vs 20 concurrentes

| Modo | Tareas | Tiempo total |
|---|---|---|
| Secuencial (20 tareas de 1 URL, procesadas de a una) | 20 | **4.718 s** |
| Concurrente (1 tarea con las 20 URLs al mismo tiempo) | 1 | **0.748 s** |

**Speedup: 6.31×**

Interpretación. Cada GET a `example.com` toma ~0.23 s (conexión + TLS +
respuesta). En modo secuencial, 20 de eso multiplica: 4.7 s. En modo
concurrente, las 20 esperas de red **se solapan** (clase 18, I/O-bound: las
esperas son "gratis" en CPU y el loop las intercalá) — el total cae a ~la
duración de la más lenta, más el costo de la conexión de pool — de ahí los
0.75 s. El speedup no es 20× exacto porque el protocolo permite. La ganancia
viene en reducir el número de esperas a un máximo, no a su suma.

### M2 — El event loop bloqueado: CPU en el loop vs en el executor

Durante un `hashear` de 3M iteraciones (~3.0 s en ambos modos), se lanzó un
`GET /estadisticas` cada 50 ms y se midió el *peor atraso*:

| Modo | GETs que pasaron en ese lapso | Latencia media | Peor atraso |
|---|---|---|---|
| `en_event_loop: true` (CPU en la corrutina) | **1** | 3066.53 ms | **3066.31 ms** |
| Con `run_in_executor` (el modo normal del sistema) | **57** | **3.37 ms** | **7.34 ms** |

Interpretación (y es el punto de toda la materia):

- **Sin executor**: el event loop quedó congelado exactamente por la duración
  del cálculo (~3 s). El único request emitido en ese lapso tardó 3.066 s en
  llegar. Y no es solo el GET: *ningún* timer de timeout se dispara, *ningún*
  otro pedido se completa (la pereza) — el servidor "pasa a estar colgado
  desde fuera". Es la característica del scheduling cooperativo: la tarea que
  no cede (clase 18) congela a todas.
- **Con executor**: 57 requests en el mismo lapso con una latencia media de
  **3.4 ms** y un peor de **7.3 ms** — casi lo mismo que la medición de la
  clase 21 (`6.3 ms` con executor, para un hash mayor: 4807 ms de atraso sin
  executor vs 6.3 con). El cálculo no corre más rápido: corre en un proceso
  aparte y deja libre el event loop para todos los demás.

Nota técnica: a la primera corrida, el modo con executor marinó un atraso de
~1 s en el primer GET. Era el arranque en frío del pool: el primer
`run_in_executor` hacía levantar los procesos del `forkserver`. El espíritu
de la clase 22 es "el pool se arma una vez al inicio" — así que lo completamos con
un mini-hash de calentamiento en `iniciar()`, y desde entonces los números quedan limpios.

### M3 — Techo del pool: dónde se degradan los tiempos

Se enviaron N tareas `esperar` de 1.0 s de golpe (N = 1, 3, 6, 12, 24, 48, 96)
y se midió el tiempo total y el atraso de cola (entre `creada` y `empezo`):

| N | Tiempo total | Techo teórico (3 workers) | Atraso medio de cola | Peor atraso |
|---|---|---|---|---|
| 1 | 1.03 s | 0.33 s | 2 ms | 2 ms |
| 3 | 1.06 s | 1.00 s | 2 ms | 2 ms |
| 6 | 1.99 s | 2.00 s | 492 ms | 983 ms |
| 12 | 4.01 s | 4.00 s | 1.473 s | 2.948 s |
| 24 | 7.88 s | 8.00 s | 3.438 s | 6.875 s |
| 48 | 15.69 s | 16.00 s | 7.343 s | 14.685 s |
| 96 | 31.46 s | 32.00 s | 15.191 s | 30.397 s |

Interpretación. Con 3 workers, la capacidad de servicio es ~3 tareas de 1 s
por segundo — y los números lo confirman al límite de precisión (el tiempo
total es casi exacto al techo teórico `ceil(N/3) × 1 s`). La cola **no** es
el cuello: el pool sí. En que se nota es en la *latencia extra*: el ultimo en
llegar espera su turno (N=96 ⇒ ~30 s de atraso), aunque el worker en sí
tarea cada una en 1 s. Es el trade-off clásico del patrón
productor-consumidor (clase 21): desacoplar productor/consumidor significa
absorber picos con cola, y el costo se paga en latencia esperada.

¿Dónde está el límite? En N=100 (`COLA_MAXSIZE`): las tareas después de eso
rechazan con 503. Es la misma decisión de diseño I/O general de la clase 21:
en un servidor que acepta pedidos de afuera el límite es parte del diseño,
aceptando que el "fallo" visible es saludable (se restaura, en vez de
comerse las tareas en memoria).

### Robustez (probado con curl, scripts del enunciado)

**1. Cancelar una `descargar` a mitad de una descarga real.** La tarea de
descarga está con 6 URLs lentas (`httpbin.org/delay/3`), y, un segundo
después de lanzarla, `DELETE`. Resultado:

- Pasa a `cancelada` de inmediato: no espera a la red.
- Los recursos en vuelo se limpian meses antes de último caso — la
  `ClientSession` es usada `async with`, y sus timeouts por URL se apagan con
  la salida de la corrutina. Los contextos de aiohttp fueron la base usada,
  tal como la clase 20 enseña la carrera: cancelación limpias con los
  bloques `async with`/`finally`, no con código especial de cleanup.
- La API **sigue viva** durante y después (el `GET /estadisticas` = 200 en
  ~7 ms mientras se cancelaba la tarea).

**2. Apagado ordenado con SIGINT (Ctrl+C), con tareas de 30 s en curso y cola cargada:**

1. uvicorn recibe la señal y para de aceptar pedidos (la primera pata del
   apagado ordenado, que la consigna pide).
2. Nuestro `lifespan` apaga el gestor: primero marca las pendientes como
   `cancelada` (no arrancan) y configura `aceptando = False`.
3. Espera con límite (`LIMITE_APAGADO` = 10 s) a las tareas en curso. Las
   de 30 s no alcanzan: al vencer el límite se cancelan
   (`Task.cancel()` sobre las sub-tareas) y quedan `cancelada`.
4. Con la cola vacía, una pastilla por worker (salen al instante), libera el
   pool de procesos y se volca el estado a
   `volcados/estado_<timestamp>.json`.

**Verificado** en tres formas: SIGINT y SIGTERM sobre la API local, y
`docker compose stop` contra el contenedor (que confirma también el
`stop_grace_period`: Docker espera 20 s, más que los 10 s del límite, para no
mandar `SIGKILL` en pleno volcado — el volcado queda escrito en el volumen
del host). Además la suite de tests tiene uno específico para el caso
difícil: cola cargada + límite vencido, y vérifica que el apagado vuelva
acotado y que las pendientes quedaron `cancelada` "cancelada durante el
apagado". Ese test descubrió el problema fino del punto 4 (cancelar al
worker en vez de a la sub-tarea), ya corregido en el código y contado en §2.

---

## 4. Conceptos del curso aplicados

La relación entre partes del sistema y clases del curso:

| Parte del código | Concepto | Clase |
|---|---|---|
| `uvicorn.run(app,...)` + la guarda `__main__` | Tres capas: uvicorn (loop)/ASGI/FastAPI; spawn re-importa el módulo | 19 + consigna |
| El event loop que intercala todo | Bucle de eventos sobre `selectors` (uvicorn lo corre por debajo) | 17 |
| Cada `async def` del sistema | Generadores → `send()` → corrutinas (se puede verificar con `.send()`) | 18 |
| `asyncio.Queue` + workers en `gestor.py` | Productor-consumidor entre corrutinas (en la clase 11, entre threads) | 21 (y 11) |
| `PASTILLA` con `object()`; salen ordenados | Worker de la clase 21 (el bucle infinito + centinela) | 21 |
| `task_done()` dentro del `finally` | Contador interno de la cola; sin él `join()` espera eternamente | 21 |
| Sin `Lock` en registro ni estadísticas | Cambio de contexto solo en `await`: atomícidad exacta por construcción | 20 |
| `gather`+`ClientSession` en `descargar` | I/O concurrente de red + reuso del cliente | 20 |
| Timeout por URL y timeout por tarea | "Siempre timeout" en operaciones de red; timeout cancela | 20 |
| `DELETE` → `Task.cancel()` → `CancelledError` | Cancelación: inyección de excepción en el próximo `await` | 20 |
| Distinguir cancel del worker vs de la sub-tarea (`Task.cancelling()`) | Cancelar la unidad correcta (tarea, no worker) en el apagado | 20/21 |
| Context managers y `finally` en `tareas.py` | Limpieza en cancelación | 20 |
| `run_in_executor` + `ProcessPoolExecutor` | El cálculo sale del loop; GIL: procesos reales para CPU | 21/22 |
| `hashear_bloqueante` top-level | Pickle: lambdas no se pueden mandar a procesos | 22 |
| El pool al arrancar y calentado | Crear el pool una vez, no por pedido | 21/22 |
| `maxsize` + 503 en el POST | Backpressure | 21 |
| Todos los endpoints `async` (y sin bloqueo adentro) | El endpoint async corre en el loop; con bloqueo dentro sería peor que `def` (medido en clase 19: 3.03s vs 1.06s) | 19 |

Dos decisiones que se apartan de las clases — del comportamiento deliberado:

- **No instalamos `loop.add_signal_handler()` propios** (la clase 20 los
  usa): uvicorn ya instalación los handlers de `SIGTERM`/`SIGINT`, y
  nuestro apagado entra por el `lifespan` (el orden ahí es: primero para de
  aceptar pedidos, después corre nuestro `apagar()`, que es lo que la
  consigna documenta como "dejar de aceptar tareas nuevas"). El self-pipe se
  encuentra detrás de uvicorn — al nivel que nosotros no lo re-implementamos.
- **`asyncio.timeout()` no lo usamos**: el timeout es con
  `asyncio.wait_for()` — el mismo concepto (la clase 20 presenta ambos):

---

## 5. Limitaciones conocidas

- **Estado no se recupera al arrancar.** Solo vive en memoria y los volcados
  son informativos (se loguean, no re-encolan tareas). La consigna pide el
  volcado; restaurar el estado es otro tema: que hacer con las `ejecutando`
  al morir es una pregunta que no tiene respuesta clara sin base de datos.
- **`DELETE` no interrumpe un `hashear` en curso en el executor.** Discutido
  en §2: sin un `await` en el proceso no hay dónde inyectar la
  `CancelledError`, y `concurrent.futures` solo permite cancelar tareas no
  arrancadas (clase 22). La tarea queda "pendiente de cancelación" hasta que
  el proceso del hash termine — el worker queda ocupado mientras. Interrumpir
  procesos exactamente en ejecución demandaría gestión de procesos manual
  (SIGKILL a los hijos del pool), con la zona oscura de liberación de
  recursos que ese camino trae.
- **Corre solo con un proceso de uvicorn.** Trade-off de clase 19 que ya
  explicamos: con `--workers N` el estado en memoria no llega compartido.
- **Cola limitada (maxsize=100)**: para avalanchas se rechaza con 503 en vez
  de crecer la cola sin cota — es deliberado, pero es igual un límite, cierto
  WORKLOAD muy grande no lo atraviesa.
- **Un worker muerto deja su tarea como `ejecutando` para siempre** si el
  bug es en el propio bucle del worker (no la tarea), porque el que quedó
  esperando era justamente él; en los casos normales (excepciones de tarea)
  está contemplado (§2).
- **Sin reintentos ni prioridades** — son bonus opcionales de la consigna.
- **El historial de tareas crece sin límite.** Las terminadas nunca se borran
  del registro: con muchísimas tareas activas en la vida del servidor, el
  dict crece. Deliberado (la consigna no pide purga; borrar implicaría
  decidir qué pasa con las estadísticas acumuladas).
- **Una `pendiente` cancelada sigue ocupando su lugar en la cola** hasta que
  un worker la saque y la saltee (la `asyncio.Queue` no permite borrar del
  medio). Con `COLA_MAXSIZE=100`, esas tareas siguen contando para el
  límite un ratito más.

---

## 6. Lo que aprendiste

> **[SECCIÓN PERSONAL — se completa con Lucas.]**
> La consigna pide 2–3 párrafos personales que la IA no puede escribir. Puntos
> por si ayudan como esqueleto: ¿qué concepto terminó de aclarar haberlo
> escrito vos (por ejemplo, qué significa *exactamente* bloquear el event
> loop viendo el M2), cuál bug costó más (¿el futuro que no esperaba? ¿la
> cancelación el worker?), qué harías distinto si arrancaras de cero.

---

*Trabajo Práctico Nº 2 — Computación II — 2026*
