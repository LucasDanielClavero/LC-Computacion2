import time
from procfs import leer_stat_global, leer_loadavg, leer_meminfo, leer_uptime

def correr_analizador_sistema(cola_pids, snapshot, lock):
    """
    Proceso analizador del Sistema Global.
    Lee /proc/stat, /proc/loadavg, /proc/meminfo y /proc/uptime.
    """
    print("[Analizador Sistema] Iniciado y listo.")
    
    # Historial para calcular el delta de CPU %
    historial_cpu = {"total": 0, "idle": 0}
    
    while True:
        # Aunque es global y no usa los PIDs, consumimos la cola para mantener la arquitectura
        # y no bloquear al recolector
        _ = cola_pids.get()
        
        stat = leer_stat_global()
        load = leer_loadavg()
        mem = leer_meminfo()
        uptime = leer_uptime()
        
        # Cálculo de CPU Global (Deltas)
        delta_total = stat["total"] - historial_cpu["total"]
        delta_idle = stat["idle"] - historial_cpu["idle"]
        
        cpu_pct = 0.0
        if delta_total > 0:
            cpu_pct = 100.0 * (1.0 - (delta_idle / delta_total))
            
        # Actualizamos historial
        historial_cpu["total"] = stat["total"]
        historial_cpu["idle"] = stat["idle"]
        
        datos_sistema = {
            "cpu_global_pct": round(max(0.0, cpu_pct), 1),
            "btime": stat.get("btime", 0),
            "loadavg": load,
            "memoria": mem,
            "uptime": uptime
        }
        
        with lock:
            snapshot["sistema"] = datos_sistema