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
