import time
from multiprocessing import Process, Queue, Manager, Lock

# Importamos nuestro módulo de señales
import senales

from recolector import correr_recolector
from analizadores.resumen import correr_analizador_resumen
from analizadores.memoria import correr_analizador_memoria
from analizadores.fds import correr_analizador_fds
from analizadores.scheduling import correr_analizador_scheduling
from analizadores.senales import correr_analizador_senales
from analizadores.entorno import correr_analizador_entorno
from analizadores.jerarquia import correr_analizador_jerarquia
from tui import desplegar_tui

def main():
    # 0. Registrar los handlers de señales externas (SIGHUP, SIGUSR1, SIGUSR2, SIGINT)
    senales.registrar_senales()

    # 1. Creamos las 7 colas de comunicación
    colas = {
        "resumen": Queue(),
        "memoria": Queue(),
        "fds": Queue(),
        "scheduling": Queue(),
        "senales": Queue(),
        "entorno": Queue(),
        "jerarquia": Queue()
    }
    
    manager = Manager()
    snapshot_global = manager.dict()
    lock_snapshot = Lock()
    
    # 2. Proceso Recolector
    proc_recolector = Process(
        target=correr_recolector, 
        args=(list(colas.values()),)
    )
    
    # 3. Mapeo de Analizadores
    procesos_analizadores = [
        Process(target=correr_analizador_resumen, args=(colas["resumen"], snapshot_global, lock_snapshot)),
        Process(target=correr_analizador_memoria, args=(colas["memoria"], snapshot_global, lock_snapshot)),
        Process(target=correr_analizador_fds, args=(colas["fds"], snapshot_global, lock_snapshot)),
        Process(target=correr_analizador_scheduling, args=(colas["scheduling"], snapshot_global, lock_snapshot)),
        Process(target=correr_analizador_senales, args=(colas["senales"], snapshot_global, lock_snapshot)),
        Process(target=correr_analizador_entorno, args=(colas["entorno"], snapshot_global, lock_snapshot)),
        Process(target=correr_analizador_jerarquia, args=(colas["jerarquia"], snapshot_global, lock_snapshot)),
    ]
    
    # 4. Iniciar todos los procesos
    proc_recolector.start()
    for p in procesos_analizadores:
        p.start()
        
    try:
        # Le damos 1.5 segundos para la primera recolección antes de abrir el TUI
        time.sleep(1.5)
        
        # 5. Iniciar la interfaz TUI (que procesará flags de señales periódicamente)
        desplegar_tui(snapshot_global, lock_snapshot)

    except KeyboardInterrupt:
        pass
    finally:
        print("\n[!] Finalizando procesos del monitor de forma limpia...")
        
        # A. Agrupamos todos los procesos hijos
        todos_los_procesos = [proc_recolector] + procesos_analizadores
        
        # B. Liberamos las colas para evitar bloqueos de hilos (cancel_join_thread)
        for q in colas.values():
            q.cancel_join_thread()
            q.close()
            
        # C. Solicitamos la terminación de cada proceso hijo
        for p in todos_los_procesos:
            if p.is_alive():
                p.terminate()
                
        # D. Cierre con timeout e inactivación total (limpieza de Zombies)
        for p in todos_los_procesos:
            p.join(timeout=0.5)
            if p.is_alive():
                p.kill() # Por si no respondió a SIGTERM, forzamos SIGKILL
                p.join()
                
        print("[✓] Monitor finalizado con éxito.")

if __name__ == '__main__':
    main()