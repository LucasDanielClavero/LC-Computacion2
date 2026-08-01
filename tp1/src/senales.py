import signal
import sys
import json
import time

# Flags globales para comunicar la señal al loop principal sin bloquear
FLAG_RECARGAR_CONFIG = False
FLAG_HACER_DUMP = False
FLAG_MODO_VERBOSE = False
FLAG_SHUTDOWN = False

def handler_sighup(signum, frame):
    """SIGHUP: Marcar para recargar config.json."""
    global FLAG_RECARGAR_CONFIG
    FLAG_RECARGAR_CONFIG = True

def handler_sigusr1(signum, frame):
    """SIGUSR1: Marcar para hacer dump del snapshot actual."""
    global FLAG_HACER_DUMP
    FLAG_HACER_DUMP = True

def handler_sigusr2(signum, frame):
    """SIGUSR2: Alternar modo verbose."""
    global FLAG_MODO_VERBOSE
    FLAG_MODO_VERBOSE = not FLAG_MODO_VERBOSE

def handler_shutdown(signum, frame):
    """SIGINT / SIGTERM: Marcar inicio de shutdown limpio."""
    global FLAG_SHUTDOWN
    FLAG_SHUTDOWN = True

def registrar_senales():
    """Registra los handlers del monitor."""
    signal.signal(signal.SIGHUP, handler_sighup)
    signal.signal(signal.SIGUSR1, handler_sigusr1)
    signal.signal(signal.SIGUSR2, handler_sigusr2)
    signal.signal(signal.SIGINT, handler_shutdown)
    signal.signal(signal.SIGTERM, handler_shutdown)

def procesar_flags_senales(snapshot_dict, ruta_config="config.json"):
    """
    Funcion ejecutada en el loop principal (fuera del handler).
    Realiza las tareas pesadas de manera sincrona y segura.
    """
    global FLAG_RECARGAR_CONFIG, FLAG_HACER_DUMP

    # 1. Recargar Configuración (SIGHUP)
    if FLAG_RECARGAR_CONFIG:
        FLAG_RECARGAR_CONFIG = False
        try:
            with open(ruta_config, "r") as f:
                config_nueva = json.load(f)
            # Guardamos la nueva config dentro del snapshot compartido para que todos la vean
            snapshot_dict["config"] = config_nueva
        except Exception as e:
            pass

    # 2. Hacer Dump de Snapshot (SIGUSR1)
    if FLAG_HACER_DUMP:
        FLAG_HACER_DUMP = False
        try:
            timestamp = int(time.time())
            nombre_archivo = f"dump_{timestamp}.json"
            # Hacemos una copia local para no bloquear la memoria compartida mientras escribimos a disco
            datos_snapshot = dict(snapshot_dict)
            with open(nombre_archivo, "w") as f:
                json.dump(datos_snapshot, f, indent=4, default=str)
        except Exception as e:
            pass