import time
from procfs import (
    leer_fds_proceso, 
    leer_limite_fds, 
    leer_io_proceso
)

def correr_analizador_fds(cola_pids, snapshot, lock, intervalo_val):
    """
    Proceso analizador de Descriptores de Archivos e I/O.
    """
    print("[Analizador FDs] Iniciado y listo.")
    
    while True:
        # 1. Recibimos la lista de PIDs del Recolector
        pids = cola_pids.get()
        while not cola_pids.empty():
            try:
                pids = cola_pids.get_nowait()
            except:
                break
        
        datos_fds = {}
        
        # 2. Analizamos los FDs e I/O de cada proceso
        for pid in pids:
            lista_fds = leer_fds_proceso(pid)
            limite_fds = leer_limite_fds(pid)
            io_stats = leer_io_proceso(pid)
            
            datos_fds[pid] = {
                "pid": pid,
                "cant_fds": len(lista_fds),
                "limite_fds": limite_fds,
                "io": io_stats,
                "descriptores": lista_fds  # Detalle completo para la vista extendida
            }
            
        # 3. Guardamos en la memoria compartida
        with lock:
            snapshot["fds"] = datos_fds
            
        time.sleep(intervalo_val.value)