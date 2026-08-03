import sys
from multiprocessing import Process, Manager, Queue, Lock
import senales

# --- IMPORTAMOS LOS 7 ANALIZADORES OBLIGATORIOS ---
from analizadores.resumen import correr_analizador_resumen
from analizadores.memoria import correr_analizador_memoria
from analizadores.fds import correr_analizador_fds
from analizadores.threads import correr_analizador_threads
from analizadores.senales import correr_analizador_senales
from analizadores.scheduling import correr_analizador_scheduling
from analizadores.sistema import correr_analizador_sistema

# Importamos el Recolector y la Interfaz Gráfica (TUI)
from recolector import correr_recolector  # <-- Ajustá este import si tu recolector se llama distinto
from tui import desplegar_tui

def main():
    # 1. Configuramos el manejo de señales (SIGHUP, SIGINT, SIGTERM)
    senales.configurar_manejadores_senales()

    # 2. Inicializamos la Memoria Compartida (Snapshot y Lock)
    manager = Manager()
    snapshot_global = manager.dict()
    lock_snapshot = manager.Lock()

    # 3. Inicializamos las colas IPC para comunicar el Recolector con los Analizadores
    colas = {
        "resumen": Queue(),
        "memoria": Queue(),
        "fds": Queue(),
        "threads": Queue(),
        "senales": Queue(),
        "scheduling": Queue(),
        "sistema": Queue()
    }

    # 4. Definimos los procesos
    procesos = []

    # Proceso Recolector (le pasamos el diccionario de colas)
    p_recolector = Process(target=correr_recolector, args=(colas,))
    procesos.append(p_recolector)

    # Procesos Analizadores (Los 7 obligatorios de la consigna)
    procesos.append(Process(target=correr_analizador_resumen, args=(colas["resumen"], snapshot_global, lock_snapshot)))
    procesos.append(Process(target=correr_analizador_memoria, args=(colas["memoria"], snapshot_global, lock_snapshot)))
    procesos.append(Process(target=correr_analizador_fds, args=(colas["fds"], snapshot_global, lock_snapshot)))
    procesos.append(Process(target=correr_analizador_threads, args=(colas["threads"], snapshot_global, lock_snapshot)))
    procesos.append(Process(target=correr_analizador_senales, args=(colas["senales"], snapshot_global, lock_snapshot)))
    procesos.append(Process(target=correr_analizador_scheduling, args=(colas["scheduling"], snapshot_global, lock_snapshot)))
    procesos.append(Process(target=correr_analizador_sistema, args=(colas["sistema"], snapshot_global, lock_snapshot)))

    # 5. Iniciamos todos los procesos en paralelo
    print("[Main] Iniciando procesos (Recolector + 7 Analizadores)...")
    for p in procesos:
        p.start()

    # 6. Lanzamos la TUI en el hilo principal
    try:
        desplegar_tui(snapshot_global, lock_snapshot)
    except KeyboardInterrupt:
        pass
    finally:
        # 7. Limpieza y apagado ordenado (Graceful Shutdown)
        print("\n[Main] Apagando el sistema...")
        senales.FLAG_SHUTDOWN = True
        
        # 1. Pedimos amablemente que se cierren (SIGTERM)
        for p in procesos:
            p.terminate()
            
        # 2. Esperamos que terminen, si están trabados los forzamos (SIGKILL)
        for p in procesos:
            p.join(timeout=0.5)  # Esperamos medio segundo por proceso
            if p.is_alive():
                p.kill()         # Lo matamos forzadamente si se quedó bloqueado
                p.join()
                
        print("[Main] Todos los procesos finalizados correctamente.")

if __name__ == "__main__":
    main()