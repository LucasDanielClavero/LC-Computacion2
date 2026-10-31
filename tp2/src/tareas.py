"""
Las 3 tareas obligatorias del TP:
- esperar:    I/O simulado (asyncio.sleep)
- descargar:  I/O real (descarga de URLs con aiohttp)
- hashear:    CPU-bound (SHA-256 iterado, corre en un proceso aparte)
"""

import asyncio
import hashlib
import time

import aiohttp


# ---------------------------------------------------------------
# Tarea: esperar (I/O simulado)
# Sirve para probar cancelacion, timeouts y ver el estado en vivo.
# IMPORTANTE: asyncio.sleep() NO bloquea el event loop, a diferencia
# de time.sleep() que si lo haria (y por eso esta prohibido en el TP).
# ---------------------------------------------------------------
async def ejecutar_esperar(params):
    segundos = params["segundos"]
    await asyncio.sleep(segundos)
    return {"segundos_dormidos": segundos}


# ---------------------------------------------------------------
# Tarea: descargar (I/O real, I/O-bound)
# Descarga MUCHAS urls al mismo tiempo con asyncio.gather + aiohttp.
# Como es I/O, mientras una descarga espera datos, las otras avanzan.
# Por eso 20 urls tardan aproximadamente lo que la mas lenta,
# no la suma de todas.
# ---------------------------------------------------------------
async def _descargar_una(sesion, url):
    """Descarga una sola url y devuelve codigo, tamano y tiempo."""
    t0 = time.perf_counter()
    try:
        async with sesion.get(url) as resp:
            datos = await resp.read()
            return {
                "url": url,
                "codigo": resp.status,
                "tamano_bytes": len(datos),
                "tiempo_s": round(time.perf_counter() - t0, 3),
            }
    except Exception as e:
        return {
            "url": url,
            "codigo": None,
            "error": repr(e),
            "tiempo_s": round(time.perf_counter() - t0, 3),
        }


async def ejecutar_descargar(params):
    urls = params["urls"]
    # timeout por url, para no quedarnos colgados para siempre
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as sesion:
        # gather lanza TODAS las descargas al mismo tiempo (concurrentes)
        resultados = await asyncio.gather(
            *[_descargar_una(sesion, u) for u in urls]
        )
    return list(resultados)


# ---------------------------------------------------------------
# Tarea: hashear (CPU-bound)
# Aplica SHA-256 N veces sobre el texto. Es CPU puro: no hay esperas,
# con lo cual NUNCA cede el control y travaria el event loop.
# Por eso esta funcion NO se corre como corrutina: el gestor la manda
# a un ProcessPoolExecutor con run_in_executor (ver gestor.py).
# Es una funcion "pura al nivel del modulo" porque ProcessPoolExecutor
# necesita poder encontrarla por nombre (sin objetos ni closures).
# ---------------------------------------------------------------
def hashear_bloqueante(texto, iteraciones):
    dato = texto.encode()
    for _ in range(iteraciones):
        dato = hashlib.sha256(dato).digest()
    return dato.hex()
