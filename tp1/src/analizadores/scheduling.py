from procfs import (
    leer_status_proceso,
    leer_scheduling_stat
)

def correr_analizador_scheduling(cola_pids, snapshot, lock):
    """
    Proceso analizador de Planificación (Scheduling).
    Cumple con los requisitos obligatorios de la consigna.
    """
    print("[Analizador Scheduling] Iniciado y listo.")
    
    while True:
        # 1. Recibimos la lista de PIDs del Recolector
        pids = cola_pids.get()
        
        datos_sched = {}
        
        # 2. Analizamos las métricas de scheduling para cada proceso
        for pid in pids:
            status = leer_status_proceso(pid)
            if not status:
                continue
                
            stat_data = leer_scheduling_stat(pid)
            
            # Cambios de contexto desde /proc/<pid>/status
            v_ctx = int(status.get('voluntary_ctxt_switches', 0))
            nv_ctx = int(status.get('nonvoluntary_ctxt_switches', 0))
            
            # Afinidad de CPU
            cpu_affinity = status.get('Cpus_allowed_list', 'N/A')
            
            datos_sched[pid] = {
                "pid": pid,
                "priority": stat_data["priority"],
                "nice": stat_data["nice"],
                "rt_priority": stat_data["rt_priority"],
                "policy": stat_data["policy_name"],
                "cpu_affinity": cpu_affinity,
                "voluntary_ctx": v_ctx,
                "nonvoluntary_ctx": nv_ctx,
                "utime": stat_data["utime"],
                "stime": stat_data["stime"],
                "sid": stat_data["sid"],
                "pgid": stat_data["pgid"]
            }
            
        # 3. Guardamos en el snapshot compartido de forma segura
        with lock:
            snapshot["scheduling"] = datos_sched