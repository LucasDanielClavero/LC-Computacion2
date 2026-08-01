from procfs import leer_status_proceso

def correr_analizador_jerarquia(cola_pids, snapshot, lock):
    """
    Proceso analizador de Jerarquía (relaciones Padre-Hijo).
    """
    print("[Analizador Jerarquía] Iniciado y listo.")
    
    while True:
        # 1. Recibimos PIDs del Recolector
        pids = cola_pids.get()
        
        relaciones_padres = {}  # {pid: ppid}
        hijos_por_padre = {}    # {ppid: [hijo1, hijo2, ...]}
        
        # 2. Mapeamos la relación
        for pid in pids:
            status = leer_status_proceso(pid)
            if not status:
                continue
                
            ppid = int(status.get('PPid', 0))
            relaciones_padres[pid] = ppid
            
            if ppid not in hijos_por_padre:
                hijos_por_padre[ppid] = []
            hijos_por_padre[ppid].append(pid)
            
        # 3. Guardamos la estructura del árbol en la memoria compartida
        with lock:
            snapshot["jerarquia"] = {
                "padres": relaciones_padres,
                "hijos": hijos_por_padre
            }