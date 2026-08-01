import time
from procfs import listar_pids

def correr_recolector(lista_colas, intervalo=2.0):
    """
    Proceso recolector central.
    Envía la lista de PIDs activos a todas las colas registradas.
    """
    print("[Recolector] Iniciado...")
    while True:
        pids = listar_pids()
        for cola in lista_colas:
            cola.put(pids)
        time.sleep(intervalo)