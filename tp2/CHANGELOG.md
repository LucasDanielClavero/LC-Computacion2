# CHANGELOG — TP2: Plataforma de Tareas Distribuidas

Historial de versiones del TP2. Cada entry corresponde (aproximadamente) a un commit.

---

## v0.1 — Primera versión funcional

**Fecha:** 31/10/2026
**Estado:** cumple lo funcional de la consigna. Faltan mediciones, informe y bonus.

### Qué incluye

- **API HTTP completa (FastAPI)** con los 5 endpoints obligatorios:
  - `POST /tareas` — encola una tarea y responde inmediatamente (id + estado inicial)
  - `GET /tareas` — lista las tareas, con filtro opcional `?estado=`
  - `GET /tareas/{id}` — estado y resultado de una tarea
  - `DELETE /tareas/{id}` — cancela una tarea **pendiente o en ejecución**
  - `GET /estadisticas` — totales por estado, tiempo promedio, workers ocupados
- **Los 3 tipos de tarea obligatorios:**
  - `esperar` — I/O simulado (`asyncio.sleep`)
  - `descargar` — I/O real, descarga concurrente (`asyncio.gather` + `aiohttp`), devuelve código, tamaño y tiempo por url
  - `hashear` — CPU-bound (SHA-256 iterado sobre N), se ejecuta en un proceso aparte
- **Pool de workers** configurable (`NUM_WORKERS`, default 3): corrutinas consumiendo de un `asyncio.Queue`
- **Executor para CPU-bound:** `hashear` corre en un `ProcessPoolExecutor` vía `run_in_executor`, para no congelar el event loop
- **Timeout por tarea** (`timeout_s` en el POST, default global `TIMEOUT_DEFAULT`): al vencer, la tarea pasa a `fallida` con el motivo
- **Cancelación limpia:** `DELETE` sobre una tarea en ejecución la interrumpe sin matar al worker ni dejar corrutinas huérfanas
- **Apagado ordenado** (SIGTERM/SIGINT): deja de aceptar tareas nuevas, espera con límite (`LIMITE_APAGADO`, 10s) a las que están en curso, cancela lo que quedó, y **volca el estado** a `volcados/estado_<timestamp>.json`
- Al arrancar, **reporta por log si hay volcados previos**
- **Docker:** `Dockerfile` + `docker-compose.yml`, todo levanta con `docker compose up --build`, API accesible en `localhost:8000`, los volcados persisten en el host
- Guarda `if __name__ == "__main__"` (necesaria para el `ProcessPoolExecutor` en macOS/Windows por el modo `spawn`)
- README con uso (curl) y estructura del código

### Verificado con pruebas reales

- POST responde en ms mientras la tarea tarda 20s
- Durante un hash pesado, `GET /tareas` responde en ~5 ms (el event loop no se bloquea)
- Cancelación de tarea en ejecución → estado `cancelada`
- Timeout → estado `fallida` con el motivo
- SIGTERM → apagado ordenado + volcado correcto

### Pendiente

- [ ] Las 3 mediciones obligatorias (concurrencia I/O, event loop bloqueado con/sin executor, techo del pool)
- [ ] README: decisiones de diseño argumentadas + conexión con las clases del curso
- [ ] Bonus (opcional)
