import time
from procfs import (
    leer_status_proceso, 
    leer_memoria_status, 
    leer_maps_proceso, 
    leer_page_faults,           # Importar nueva función
    agrupar_segmentos_memoria   # Importar nueva función
)

def correr_analizador_memoria(cola_pids, snapshot, lock, intervalo_val):
    """
    Proceso analizador de la vista Memoria.
    Recibe PIDs y extrae las métricas Vm*, faults, y regiones mapeadas (maps) agrupadas.
    """
    print("[Analizador Memoria] Iniciado y listo.")
    
    while True:
        pids = cola_pids.get()
        while not cola_pids.empty():
            try:
                pids = cola_pids.get_nowait()
            except:
                break
        datos_memoria = {}
        
        for pid in pids:
            status = leer_status_proceso(pid)
            if not status:
                continue
                
            metricas_mem = leer_memoria_status(status)
            regiones_maps = leer_maps_proceso(pid)
            faults = leer_page_faults(pid)
            segmentos = agrupar_segmentos_memoria(regiones_maps)
            
            datos_memoria[pid] = {
                "pid": pid,
                "vmsize": metricas_mem["vmsize"],
                "vmrss": metricas_mem["vmrss"],
                "vmdata": metricas_mem["vmdata"],
                "vmstk": metricas_mem["vmstk"],
                "vmexe": metricas_mem["vmexe"],
                "vmlib": metricas_mem["vmlib"],
                "vmhwm": metricas_mem["vmhwm"],     # Extraído para cumplir la consigna
                "vmswap": metricas_mem["vmswap"],   # Extraído para cumplir la consigna y nutrir la TUI
                "min_faults": faults["minflt"],     # Extraído para cumplir la consigna
                "maj_faults": faults["majflt"],     # Extraído para cumplir la consigna
                "segmentos_kb": segmentos,          # Segmentos agrupados como pide la consigna
                "cant_regiones": len(regiones_maps)
            }
            
        with lock:
            snapshot["memoria"] = datos_memoria
            
        time.sleep(intervalo_val.value)