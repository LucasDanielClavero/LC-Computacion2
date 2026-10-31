# TP2 — Plataforma de Tareas Distribuidas

> **Estado: primera versión.** Cumple lo funcional de la consigna. Faltan las
> mediciones, el informe argumentado y los bonus.
>
> El historial de versiones por commit está en [CHANGELOG.md](CHANGELOG.md).

## Qué es

Un servicio al que se le encargan trabajos por HTTP, los ejecuta de forma
concurrente y permite consultar su estado y resultado.

- **API** con FastAPI: encola tareas y responde inmediatamente.
- **Cola** con `asyncio.Queue`: productores = endpoints, consumidores = workers.
- **Pool de workers**: 3 corrutinas que sacan tareas de la cola.
- **Executor de procesos** para las tareas CPU-bound (para no congelar el event loop).

### Los 3 tipos de tarea

| Tipo | Naturaleza | Cómo se ejecuta |
|------|-----------|-----------------|
| `esperar` | I/O simulado | corrutina con `asyncio.sleep()` |
| `descargar` | I/O real | corrutinas concurrentes con `asyncio.gather` + `aiohttp` |
| `hashear` | CPU-bound | `run_in_executor` → proceso aparte |

## Cómo levantar

```bash
docker compose up --build
```

La API queda en `http://localhost:8000`. La documentación automática de FastAPI en
`http://localhost:8000/docs`.

## Cómo probar (curl)

```bash
# Encargar una tarea de espera de 20 segundos
curl -X POST http://localhost:8000/tareas \
  -H 'Content-Type: application/json' \
  -d '{"tipo": "esperar", "params": {"segundos": 20}}'

# Encargar una descarga concurrente de varias urls
curl -X POST http://localhost:8000/tareas \
  -H 'Content-Type: application/json' \
  -d '{"tipo": "descargar", "params": {"urls": ["https://example.com", "https://www.python.org"]}}'

# Encargar un hash pesado (CPU) — la API queda a toda velocidad igual
curl -X POST http://localhost:8000/tareas \
  -H 'Content-Type: application/json' \
  -d '{"tipo": "hashear", "params": {"texto": "hola", "iteraciones": 5000000}}'

# Listar todas (o filtrar: ?estado=ejecutando, pendiente, completada, fallida, cancelada)
curl http://localhost:8000/tareas
curl "http://localhost:8000/tareas?estado=ejecutando"

# Estado y resultado de una tarea
curl http://localhost:8000/tareas/t1

# Cancelar una tarea (funciona tanto pendiente como en ejecucion)
curl -X DELETE http://localhost:8000/tareas/t1

# Estadisticas
curl http://localhost:8000/estadisticas

# Probar la cancelacion de una tarea en ejecucion (en otra terminal, mientras duerme)
# -> DELETE sobre esa t y pasa a "cancelada"
```

Variables de entorno (docker-compose.yml): `NUM_WORKERS`, `NUM_PROCESOS`,
`TIMEOUT_DEFAULT` (segundos, por tarea), `LIMITE_APAGADO`.

## Estructura del código

```
src/
├── main.py     # punto de entrada (uvicorn). La guarda __main__ es necesaria
│               # por el ProcessPoolExecutor en macOS/Windows (spawn)
├── api.py      # endpoints FastAPI + ciclo de vida (arranque/apagado)
├── gestor.py   # la cola, el pool de workers, timeout, cancelacion, volcado
└── tareas.py   # las 3 tareas: esperar, descargar, hashear
```

## Cosas a revisar de esta versión

- [ ] Mediciones obligatorias (concurrencia I/O, event loop bloqueado, techo del pool)
- [ ] README con decisiones de diseño argumentadas (por qué asyncio.Queue, executor, cancelación...)
- [ ] Conectar el código con las clases del curso
- [ ] Bonus (websocket, prioridades, tests, etc.)
