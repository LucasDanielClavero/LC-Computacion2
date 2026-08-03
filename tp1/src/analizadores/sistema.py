import time
from procfs import (
    leer_stat_global, leer_loadavg, leer_meminfo, leer_uptime,
    leer_stat_proceso, leer_status_proceso
)

def correr_analizador_sistema(cola_pids, snapshot, lock):
    """
    Proceso analizador del Sistema Global.
    Cumple con los requisitos obligatorios de contar estados, threads y top 3.
    """
    print("[Analizador Sistema] Iniciado y listo.")
    
    historial_cpu = {"total": 0, "idle": 0}
    
    while True:
        # 1. Ahora sí usamos la lista de PIDs
        pids = cola_pids.get()
        
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
            
        historial_cpu["total"] = stat["total"]
        historial_cpu["idle"] = stat["idle"]

        # 2. Conteo de Procesos, Estados, Zombies y Threads
        estados_count = {}
        total_threads = 0
        zombies = 0
        
        for pid in pids:
            st = leer_stat_proceso(pid)
            status = leer_status_proceso(pid)
            
            if st:
                est = st.get("estado", "U")
                estados_count[est] = estados_count.get(est, 0) + 1
                if est == 'Z':
                    zombies += 1
            
            if status:
                try:
                    total_threads += int(status.get("Threads", 0))
                except ValueError:
                    pass

        # 3. Extraer Top 3 por CPU y Memoria desde el Snapshot Compartido
        with lock:
            resumen_snap = dict(snapshot.get("resumen", {}))
            memoria_snap = dict(snapshot.get("memoria", {}))

        # Top 3 CPU (basado en ms de uso si lo tenés en tu analizador resumen)
        lista_cpu = []
        for p, inf in resumen_snap.items():
            # Adaptá esta clave según lo que devuelva tu analizador_resumen
            val_cpu = inf.get("cpu_ms", inf.get("run_time_ms", 0)) 
            lista_cpu.append((p, val_cpu, inf.get("cmdline", str(p))))
        top_cpu = sorted(lista_cpu, key=lambda x: x[1], reverse=True)[:3]

        # Top 3 Memoria (basado en VmRSS)
        lista_mem = []
        for p, inf in memoria_snap.items():
            val_mem_str = str(inf.get("vmrss", "0")).replace(" kB", "").strip()
            try:
                val_mem = int(val_mem_str)
            except ValueError:
                val_mem = 0
            lista_mem.append((p, val_mem))
        top_mem = sorted(lista_mem, key=lambda x: x[1], reverse=True)[:3]

        datos_sistema = {
            "cpu_global_pct": round(max(0.0, cpu_pct), 1),
            "btime": stat.get("btime", 0),
            "loadavg": load,
            "memoria": mem,
            "uptime": uptime,
            "total_procesos": len(pids),
            "total_threads": total_threads,
            "zombies": zombies,
            "estados": estados_count,
            "top_cpu": top_cpu,
            "top_mem": top_mem
        }
        
        with lock:
            snapshot["sistema"] = datos_sistema