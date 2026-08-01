from procfs import leer_cwd_proceso, leer_environ_proceso

def correr_analizador_entorno(cola_pids, snapshot, lock):
    """
    Proceso analizador del Entorno de Ejecución (cwd y variables de entorno).
    """
    print("[Analizador Entorno] Iniciado y listo.")
    
    while True:
        # 1. Recibimos PIDs del Recolector
        pids = cola_pids.get()
        
        datos_entorno = {}
        
        # 2. Leemos cwd y environ
        for pid in pids:
            cwd = leer_cwd_proceso(pid)
            environ = leer_environ_proceso(pid)
            
            datos_entorno[pid] = {
                "pid": pid,
                "cwd": cwd,
                "cant_vars_env": len(environ),
                "environ": environ  # Diccionario con clave: valor de las variables de entorno
            }
            
        # 3. Guardamos en el snapshot compartido
        with lock:
            snapshot["entorno"] = datos_entorno