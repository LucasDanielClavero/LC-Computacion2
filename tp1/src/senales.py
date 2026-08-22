import signal
import json
import os
import time

# Flags globales para comunicar el estado a la TUI y al Main
FLAG_SHUTDOWN = False
FLAG_RELOAD = False
FLAG_DUMP = False
FLAG_VERBOSE = False

# Self-pipe para notificar a la TUI
pipe_r, pipe_w = os.pipe()
os.set_blocking(pipe_r, False)
os.set_blocking(pipe_w, False)

def notificar_pipe():
    try:
        os.write(pipe_w, b'x')
    except (BlockingIOError, OSError):
        pass

def manejador_shutdown(sig, frame):
    """Maneja SIGINT y SIGTERM para apagar el programa."""
    global FLAG_SHUTDOWN
    FLAG_SHUTDOWN = True
    notificar_pipe()

def manejador_reload(sig, frame):
    """Maneja SIGHUP para recargar la configuración."""
    global FLAG_RELOAD
    FLAG_RELOAD = True
    notificar_pipe()

def manejador_dump(sig, frame):
    """Maneja SIGUSR1 para hacer dump del snapshot."""
    global FLAG_DUMP
    FLAG_DUMP = True
    notificar_pipe()

def manejador_verbose(sig, frame):
    """Maneja SIGUSR2 para alternar el modo verbose."""
    global FLAG_VERBOSE
    FLAG_VERBOSE = not FLAG_VERBOSE  # Hacemos un toggle (True -> False -> True)
    notificar_pipe()

def configurar_manejadores_senales():
    """Registra las señales en el sistema."""
    signal.signal(signal.SIGINT, manejador_shutdown)
    signal.signal(signal.SIGTERM, manejador_shutdown)
    
    if hasattr(signal, 'SIGHUP'):
        signal.signal(signal.SIGHUP, manejador_reload)
    
    if hasattr(signal, 'SIGUSR1'):
        signal.signal(signal.SIGUSR1, manejador_dump)
        
    if hasattr(signal, 'SIGUSR2'):
        signal.signal(signal.SIGUSR2, manejador_verbose)

def procesar_flags_senales(snapshot):
    """
    Esta función es llamada por la TUI en cada ciclo para revisar
    si hay que hacer algo basado en las señales recibidas.
    """
    global FLAG_RELOAD, FLAG_DUMP, FLAG_VERBOSE
    
    # 1. Procesar SIGHUP (Recarga de config)
    if FLAG_RELOAD:
        ruta_config = "config.json"
        try:
            if not os.path.exists(ruta_config):
                ruta_config = "../config.json"
                
            if os.path.exists(ruta_config):
                with open(ruta_config, "r") as f:
                    nueva_config = json.load(f)
                    snapshot["config"] = nueva_config
        except Exception:
            pass  # Ignoramos errores para no romper la TUI
        FLAG_RELOAD = False

    # 2. Procesar SIGUSR1 (Dump a JSON)
    if FLAG_DUMP:
        timestamp = int(time.time())
        nombre_archivo = f"dump_{timestamp}.json"
        try:
            # Convertimos el Manager.dict a un dict normal para poder serializarlo
            # (Asumiendo que los diccionarios internos son serializables)
            snapshot_dict = dict(snapshot)
            with open(nombre_archivo, "w") as f:
                json.dump(snapshot_dict, f, indent=4)
        except Exception as e:
            # En un entorno real loguearíamos esto, acá lo dejamos pasar para no romper la TUI
            pass
        FLAG_DUMP = False

    # 3. Procesar SIGUSR2 (Modo Verbose)
    # Guardamos el estado actual del flag en el snapshot para que las vistas
    # de la TUI puedan leer si deben mostrar más o menos información.
    snapshot["verbose"] = FLAG_VERBOSE