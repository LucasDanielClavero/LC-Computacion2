import os
import time
from procfs import TICKS_POR_SEGUNDO, leer_detalles_hilo

def correr_analizador_threads(cola_pids, snapshot, lock, intervalo_val):
    """
    Proceso analizador de la vista Threads (LWP).
    Calcula el uso de CPU individual por hilo.
    """
    print("[Analizador Threads] Iniciado y listo.")
    
    # Historial local para calcular deltas de CPU por hilo: {(pid, tid): (ticks, timestamp)}
    historial_cpu_hilos = {}
    
    while True:
        pids = cola_pids.get()
        while not cola_pids.empty():
            try:
                pids = cola_pids.get_nowait()
            except:
                break
        tiempo_actual = time.time()
        
        datos_threads = {}
        nuevo_historial = {}
        
        for pid in pids:
            ruta_task = f"/proc/{pid}/task"
            try:
                # Buscamos todos los TIDs dentro de la carpeta task del proceso
                tids = [int(t) for t in os.listdir(ruta_task) if t.isdigit()]
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                continue
                
            lista_hilos = []
            
            for tid in tids:
                info_hilo = leer_detalles_hilo(pid, tid)
                ticks_actuales = info_hilo["ticks"]
                cpu_porcentaje = 0.0
                
                clave_historial = (pid, tid)
                if clave_historial in historial_cpu_hilos:
                    ticks_anteriores, tiempo_anterior = historial_cpu_hilos[clave_historial]
                    delta_ticks = ticks_actuales - ticks_anteriores
                    delta_tiempo = tiempo_actual - tiempo_anterior
                    
                    if delta_tiempo > 0:
                        cpu_porcentaje = (delta_ticks / (TICKS_POR_SEGUNDO * delta_tiempo)) * 100.0
                        cpu_porcentaje = round(max(0.0, cpu_porcentaje), 1)
                
                # Actualizamos historial
                nuevo_historial[clave_historial] = (ticks_actuales, tiempo_actual)
                info_hilo["cpu_porcentaje"] = cpu_porcentaje
                lista_hilos.append(info_hilo)
                
            if lista_hilos:
                datos_threads[pid] = {
                    "pid": pid,
                    "cant_hilos": len(lista_hilos),
                    "detalle_hilos": lista_hilos
                }
                
        # Limpiamos hilos que ya murieron
        historial_cpu_hilos = nuevo_historial
            
        with lock:
            snapshot["threads"] = datos_threads
            
        time.sleep(intervalo_val.value)