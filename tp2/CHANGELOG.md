# CHANGELOG — TP2: Plataforma de Tareas Distribuidas

Historial de versiones del TP2. Cada entry corresponde (aproximadamente) a un commit.

---

## v0.2 — Correcciones según clases + mediciones + informe

**Fecha:** 01/11/2026

### Correcciones alineadas con la teoría del curso (clase 21)

- **Centinela de apagado**: la pastilla de los workers pasa de `None` a
  `object()` (`PASTILLA` en `gestor.py`), el modismo que la clase 21 enseña
  para "valor único que no se confunde con un dato".
- **Backpressure**: la cola ahora tiene `maxsize=100` (`COLA_MAXSIZE`) y el
  `POST /tareas` rechaza con **503** cuando está llena, en vez de acumular
  memoria sin límite. Con esto queda contestada también "¿Qué pasa si te
  mando 10.000 tareas de golpe?" — la 101 rechaza con 503, el resto pasa.
- **Calentamiento del pool de procesos**: un mini-hash al arrancar para que
  el `forkserver` no le pague al primer pedido un atraso de ~1 s (verificado
  en la medición M2: el peor atraso con executor bajó de ~1062 ms a 7.3 ms).

### Mejora interna (para mediciones)

- Nuevo param opcional en `hashear`: `"en_event_loop": true` ejecuta el hash
  directamente en la corrutina (bloquea el event loop a propósito). Solo
  sirve para la medición M2 — con eso se mide el gesto del event loop que
  congela. Documentado en README.

### Mediciones (A2): las 3 obligatorias, medidas en esta máquina

- **M1 — Concurrencia I/O:** 20 descargas secuenciales (4.718 s) vs 20
  concurrentes (0.748 s) → **speedup 6.31×**
- **M2 — Event loop bloqueado:** hash 3M iteraciones **directo en el loop**:
  solo 1 GET pasó en 3 s, con 3066 ms de atraso. **Con executor**: 57 GETs,
  latencia media 3.37 ms, peor atraso 7.3 ms
- **M3 — Techo del pool:** con 3 workers y tareas de 1 s, el tiempo total
  clava el techo teórico `ceil(N/3) × 1s`; el atraso de cola crece lineal
  rota con N (30 s para N=96) y a N>100 rechaza con 503
- Nuevo `scripts/mediciones.py`: reproduce las tres contra la API viva

### Robustez (A3)

- **Cancelar una `descargar` a mitad de vuelo** (6 URLs lentas, DELETE 1 s
  después) → pasa a `cancelada` inmediato, la sesión HTTP queda limpia, y la
  API sigue respondiendo en ms durante y después de la cancelación
- **SIGINT con una tarea de 60s corriendo** → apagado ordenado completo
  (deja de aceptar, espera 10s, cancela, volca), same path que SIGTERM

### Informe (A4) y código (A5)

- README reescrito como informe: arquitectura con diagrama, flujo de una
  tarea, 4 decisiones de diseño argumentadas, **las 3 mediciones con números
  e interpretación**, prácticas de robustez, mapa "concepto → clase" (17-22)
  y limitaciones conocidas
- Pase de PEP 8 en `src/` y `scripts/` (clean under pycodestyle, líneas <100)
- `docker-compose.yml` agrega el `COLA_MAXSIZE` como variable de entorno

### Pendiente

- [ ] Sección "Lo que aprendiste" del README (es personal de Lucas)
- [ ] Bonus opcionales (todavía nada)
- [ ] ultima revisión del documento entero antes de la entrega

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
