from procfs import leer_status_proceso, leer_memoria_status, leer_maps_proceso

def correr_analizador_memoria(cola_pids, snapshot, lock):
    """
    Proceso analizador de la vista Memoria.
    Recibe PIDs y extrae las métricas Vm* y las regiones mapeadas (maps).
    """
    print("[Analizador Memoria] Iniciado y listo.")
    
    while True:
        # 1. Recibimos los PIDs enviada por el Recolector
        pids = cola_pids.get()
        
        datos_memoria = {}
        
        # 2. Analizamos la memoria de cada proceso
        for pid in pids:
            status = leer_status_proceso(pid)
            if not status:
                continue
                
            metricas_mem = leer_memoria_status(status)
            regiones_maps = leer_maps_proceso(pid)
            
            datos_memoria[pid] = {
                "pid": pid,
                "vmsize": metricas_mem["vmsize"],
                "vmrss": metricas_mem["vmrss"],
                "vmdata": metricas_mem["vmdata"],
                "vmstk": metricas_mem["vmstk"],
                "vmexe": metricas_mem["vmexe"],
                "vmlib": metricas_mem["vmlib"],
                "cant_regiones": len(regiones_maps),
                "maps": regiones_maps  # Lista de mapas detallados
            }
            
        # 3. Guardamos el resultado en la Memoria Compartida de forma segura
        with lock:
            snapshot["memoria"] = datos_memoria