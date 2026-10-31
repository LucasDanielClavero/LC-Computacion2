"""
Punto de entrada de la API.

IMPORTANTE: la guarda if __name__ == "__main__" no es decoracion.
El ProcessPoolExecutor arranca distinto segun el sistema:
- Linux: fork (funciona siempre)
- macOS / Windows: spawn, que RE-IMPORTA este modulo en cada proceso hijo.
Sin esa guarda, en macOS el programa entra en un bucle infinito de
reimportacion al crear el pool.
"""

import uvicorn

from api import app

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
