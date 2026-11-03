# Comandos — TP2

Lista de los pedidos que entiende la API y qué hace cada uno. Los pruebo con
`curl`, un programa que ya viene instalado en Linux y manda pedidos HTTP
desde la terminal (es el equivalente manual a lo que hace un navegador).

## Levantar y apagar

```bash
docker compose up --build
```

Levanta el servicio. Al terminar de arrancar, la API queda en
`http://localhost:8000` y la documentación interactiva en el navegador en
`http://localhost:8000/docs`.

Para apagar: `Ctrl+C` en esa misma terminal (hace el apagado ordenado y
escribe el estado en `volcados/`), o `docker compose stop` desde otra.

## Crear tareas

Encargar una tarea que espera 10 segundos:

```bash
curl -X POST http://localhost:8000/tareas -H 'Content-Type: application/json' \
  -d '{"tipo": "esperar", "params": {"segundos": 10}}'
```

Responde al instante con algo como `{"id": "t1", "estado": "pendiente"}` — no
espera a que la tarea termine (ese id es el que usan los demás comandos).

Encargar una descarga de URLs en paralelo:

```bash
curl -X POST http://localhost:8000/tareas -H 'Content-Type: application/json' \
  -d '{"tipo": "descargar", "params": {"urls": ["https://example.com", "https://www.python.org"]}}'
```

Baja todas las urls al mismo tiempo, no una detrás de otra.

Encargar un hash pesado:

```bash
curl -X POST http://localhost:8000/tareas -H 'Content-Type: application/json' \
  -d '{"tipo": "hashear", "params": {"texto": "hola", "iteraciones": 3000000}}'
```

Tarda un par de segundos, pero el servidor se nota igual de vivo: el cálculo
corre en otro proceso, no en donde atiende los pedidos.

## Consultar

Listar todas las tareas:

```bash
curl http://localhost:8000/tareas
```

El campo `estado` va cambiando en vivo: `pendiente` → `ejecutando` →
`completada`.

Listar solo las que están en ejecución:

```bash
curl "http://localhost:8000/tareas?estado=ejecutando"
```

El filtro admite cualquier estado: `pendiente`, `ejecutando`, `completada`,
`fallida`, `cancelada`.

Ver el estado y el resultado de una:

```bash
curl http://localhost:8000/tareas/t1
```

Reemplazar `t1` por el id que te dio el POST.

Ver estadísticas:

```bash
curl http://localhost:8000/estadisticas
```

Workers ocupados, tareas en cola, totales por estado, etc.

## Cancelar

```bash
curl -X DELETE http://localhost:8000/tareas/t1
```

Sirve tanto para una pendiente como para una en ejecución. Si ya terminó
responde `409`: no hay nada que cancelar.

## Casos de error

Id inexistente:

```bash
curl http://localhost:8000/tareas/t999
```

Responde `404 Not Found`.

Tipo de tarea que no existe:

```bash
curl -X POST http://localhost:8000/tareas -H 'Content-Type: application/json' \
  -d '{"tipo": "cocinar", "params": {}}'
```

Responde `400` con el motivo.

Params inválidos (por ejemplo, un número negativo):

```bash
curl -X POST http://localhost:8000/tareas -H 'Content-Type: application/json' \
  -d '{"tipo": "esperar", "params": {"segundos": -5}}'
```

Responde `400` con el motivo: `segundos` tiene que ser un número >= 0.
