"""
Las 3 mediciones obligatorias del TP (consigna, seccion "Mediciones").

Este script corre contra una instancia ARRIBA de la API
(por defecto http://localhost:8000). Se corre asi:

    python3 scripts/mediciones.py

Requiere solo la stdlib (urllib), para que las mediciones no dependan
de la misma libreria del sistema bajo prueba.

Cada medicion imprime sus numeros. Los resultados quedan tambien
volcados a JSON en stdout, para pegarlos en el README.
"""

import json
import sys
import time
import urllib.request

BASE = "http://localhost:8000"

# ------------------------------------------------------------------
# Helpers: minimo de HTTP con la stdlib
# ------------------------------------------------------------------


def post(payload):
    req = urllib.request.Request(
        BASE + "/tareas",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return json.load(urllib.request.urlopen(req))


def get(ruta):
    with urllib.request.urlopen(BASE + ruta) as resp:
        return json.load(resp)


def esperar_estado(id_tarea, timeout=600):
    """Consulta en bucle hasta que la tarea salga de ejecucion."""
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < timeout:
        tarea = get(f"/tareas/{id_tarea}")
        if tarea["estado"] in ("completada", "fallida", "cancelada"):
            return tarea
        time.sleep(0.05)
    raise TimeoutError(f"la tarea {id_tarea} nunca termino")


def duracion(tarea):
    """Cuanto corrio (empezo -> termino), segun lo que registro el gestor."""
    return round(tarea["termino"] - tarea["empezo"], 3)


# ------------------------------------------------------------------
# M1: concurrencia I/O — 20 descargas secuenciales vs 20 concurrentes
# ------------------------------------------------------------------

def medicion_1():
    urls = ["https://example.com"] * 20

    # Secuencial: 20 tareas de 1 url, esperando cada una.
    t0 = time.perf_counter()
    ids = []
    for url in urls:
        ids.append(post({"tipo": "descargar", "params": {"urls": [url]}})["id"])
    for id_tarea in ids:
        esperar_estado(id_tarea)
    t_secuencial = time.perf_counter() - t0

    # Concurrente: 1 tarea con las 20 urls adentro (gather).
    t0 = time.perf_counter()
    id_conc = post({"tipo": "descargar", "params": {"urls": urls}})["id"]
    esperar_estado(id_conc)
    t_concurrente = time.perf_counter() - t0

    return {
        "url_repetida": urls[0],
        "modo_secuencial": {
            "tareas": 20, "tiempo_total_s": round(t_secuencial, 3),
        },
        "modo_concurrente": {
            "tareas": 1, "urls_por_tarea": 20, "tiempo_total_s": round(t_concurrente, 3),
        },
        "speedup": round(t_secuencial / t_concurrente, 2),
    }


# ------------------------------------------------------------------
# M2: el event loop bloqueado — CPU directo en el loop vs executor
# ------------------------------------------------------------------

def peor_latencia(durante, payload_cpu):
    """Manda GET /estadisticas en bucle mientras la tarea CPU corre.
    Durante un bloque maximo, los GET no fallan: se retrasan (el loop
    esta congelado y contestan recien cuando se descongela). El peor
    atraso es la medicion."""
    id_cpu = post(payload_cpu)["id"]
    atrasos = []
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < durante:
        t_get = time.perf_counter()
        try:
            get("/estadisticas")
            atrasos.append(time.perf_counter() - t_get)
        except Exception:
            pass
        time.sleep(0.05)
    tarea = esperar_estado(id_cpu)
    return {
        "duracion_cpu_s": duracion(tarea),
        "cantidad_de_gets": len(atrasos),
        "latencia_get_media_ms": round(1000 * sum(atrasos) / len(atrasos), 2),
        "peor_atraso_ms": round(1000 * max(atrasos), 2),
    }


def medicion_2():
    params = {"texto": "hola", "iteraciones": 3000000}

    con_executor = peor_latencia(3.0, {"tipo": "hashear", "params": params})
    sin_executor = peor_latencia(
        3.0, {"tipo": "hashear", "params": dict(params, en_event_loop=True)}
    )
    return {"sin_executor": sin_executor, "con_executor": con_executor}


# ------------------------------------------------------------------
# M3: techo del pool — N tareas concurrentes contra NUM_WORKERS workers
# ------------------------------------------------------------------

def medicion_3():
    # Cada tarea esperar 1.0s. Con W workers, el total minimo posible es
    # ceil(N / W) * 1.0 s. Mando todas de golpe y mido el techo real.
    resultados = []
    for n in (1, 3, 6, 12, 24, 48, 96):
        payload = {"tipo": "esperar", "params": {"segundos": 1.0}}
        ids = [post(payload)["id"] for _ in range(n)]
        t0 = time.perf_counter()
        for id_tarea in ids:
            esperar_estado(id_tarea)
        total = time.perf_counter() - t0

        # atraso de cola: cuanto esperaron entre creada y empezo
        atrasos = []
        for id_tarea in ids:
            t = get(f"/tareas/{id_tarea}")
            atrasos.append(t["empezo"] - t["creada"])
        resultados.append({
            "concurrencia": n,
            "tiempo_total_s": round(total, 2),
            "teorico_minimo_s": round(n / 3, 2),
            "atraso_medio_de_cola_s": round(sum(atrasos) / len(atrasos), 3),
            "peor_atraso_de_cola_s": round(max(atrasos), 3),
        })
    return resultados


if __name__ == "__main__":
    cual = sys.argv[1] if len(sys.argv) > 1 else "todas"
    salida = {}
    if cual in ("1", "todas"):
        print("\n=== M1: 20 descargas secuenciales vs concurrentes ===")
        salida["m1"] = medicion_1()
        print(json.dumps(salida["m1"], indent=2, ensure_ascii=False))
    if cual in ("2", "todas"):
        print("\n=== M2: event loop bloqueado (CPU en el loop vs executor) ===")
        salida["m2"] = medicion_2()
        print(json.dumps(salida["m2"], indent=2, ensure_ascii=False))
    if cual in ("3", "todas"):
        print("\n=== M3: techo del pool (tareas esperar 1s, 3 workers) ===")
        salida["m3"] = medicion_3()
        print(json.dumps(salida["m3"], indent=2, ensure_ascii=False))
    print("\n--- JSON completo ---")
    print(json.dumps(salida, indent=2, ensure_ascii=False))
