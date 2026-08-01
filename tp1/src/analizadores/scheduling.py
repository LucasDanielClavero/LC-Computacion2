from procfs import (
    leer_status_proceso,
    leer_schedstat_proceso,
    leer_scheduling_stat,
    leer_hilos_task
)

def correr_analizador_scheduling(cola_pids, snapshot, lock):
    """
    Proceso analizador de Hilos y Planificación (Scheduling).
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
                
            schedstat = leer_schedstat_proceso(pid)
            prio_nice = leer_scheduling_stat(pid)
            hilos = leer_hilos_task(pid)
            
            # Cambios de contexto desde /proc/<pid>/status
            v_ctx = int(status.get('voluntary_ctxt_switches', 0))
            nv_ctx = int(status.get('nonvoluntary_ctxt_switches', 0))
            
            datos_sched[pid] = {
                "pid": pid,
                "priority": prio_nice["priority"],
                "nice": prio_nice["nice"],
                "run_time_ms": round(schedstat["run_time"] / 1_000_000, 2), # Pasamos nanosegundos a ms
                "wait_time_ms": round(schedstat["wait_time"] / 1_000_000, 2),
                "pcount": schedstat["pcount"],
                "voluntary_ctx": v_ctx,
                "nonvoluntary_ctx": nv_ctx,
                "cant_hilos": len(hilos),
                "hilos": hilos  # Lista de TIDs y sus estados para la vista extendida
            }
            
        # 3. Guardamos en el snapshot compartido de forma segura
        with lock:
            snapshot["scheduling"] = datos_sched