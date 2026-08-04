import time
from procfs import (
    leer_status_proceso, 
    leer_stat_proceso, 
    leer_cmdline, 
    obtener_nombre_usuario, 
    TICKS_POR_SEGUNDO
)

def correr_analizador_resumen(cola_pids, snapshot, lock, intervalo_val):
    """
    Proceso analizador de la vista Resumen.
    Mantiene un historial en memoria local de los ticks de CPU para calcular el % de uso.
    """
    print("[Analizador Resumen] Iniciado y listo.")
    
    # Historial local para calcular deltas de CPU: {pid: (ticks_anteriores, timestamp_anterior)}
    historial_cpu = {}
    
    while True:
        # 1. Recibimos la lista de PIDs enviada por el Recolector
        pids = cola_pids.get()
        while not cola_pids.empty():
            try:
                pids = cola_pids.get_nowait()
            except:
                break
        tiempo_actual = time.time()
        
        datos_resumen = {}
        nuevo_historial_cpu = {}
        
        # 2. Analizamos cada proceso
        for pid in pids:
            status = leer_status_proceso(pid)
            stat = leer_stat_proceso(pid)
            
            if not status or not stat:
                continue  # El proceso murió o no se pudo leer
                
            # Uid y Gid vienen como cadenas con varios números (ej: "1000 1000 1000 1000")
            uid_str = status.get('Uid', '0').split()[0]
            gid_str = status.get('Gid', '0').split()[0]
            usuario = obtener_nombre_usuario(uid_str)
            
            # --- CÁLCULO DE CPU% ---
            ticks_actuales = stat["ticks"]
            cpu_porcentaje = 0.0
            
            if pid in historial_cpu:
                ticks_anteriores, tiempo_anterior = historial_cpu[pid]
                delta_ticks = ticks_actuales - ticks_anteriores
                delta_tiempo = tiempo_actual - tiempo_anterior
                
                if delta_tiempo > 0:
                    # Fórmula de CPU%
                    cpu_porcentaje = (delta_ticks / (TICKS_POR_SEGUNDO * delta_tiempo)) * 100.0
                    cpu_porcentaje = round(max(0.0, cpu_porcentaje), 1)
            
            # Guardamos el estado actual para la siguiente iteración
            nuevo_historial_cpu[pid] = (ticks_actuales, tiempo_actual)
            
            # Armamos el diccionario completo con todos los requerimientos del TP
            datos_resumen[pid] = {
                "pid": pid,
                "ppid": int(status.get('PPid', 0)),
                "uid": int(uid_str),
                "gid": int(gid_str),
                "usuario": usuario,
                "estado": stat["estado"],  # R, S, D, T, Z
                "cmdline": leer_cmdline(pid),
                "cpu_porcentaje": cpu_porcentaje,
                "threads": int(status.get('Threads', 1))
            }
            
        # Actualizamos el historial (limpiando PIDs muertos de lecturas viejas)
        historial_cpu = nuevo_historial_cpu
            
        # 3. Guardamos en el Snapshot Global (memoria compartida)
        with lock:
            snapshot["resumen"] = datos_resumen
            
        time.sleep(intervalo_val.value)