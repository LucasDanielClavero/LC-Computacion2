import time
from procfs import listar_pids

def correr_recolector(colas, intervalo=2.0):
    """
    Proceso recolector central.
    Envía la lista de PIDs activos a todas las colas registradas.
    """
    print("[Recolector] Iniciado...")
    while True:
        pids = listar_pids()
        
        # Iteramos sobre colas.values() para obtener los objetos Queue, 
        # no las claves string.
        for cola in colas.values():
            cola.put(pids)
            
        time.sleep(intervalo)