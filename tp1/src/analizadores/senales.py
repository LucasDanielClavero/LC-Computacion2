import time
from procfs import leer_status_proceso, decodificar_mascara_senales, nombres_desde_mascara

def correr_analizador_senales(cola_pids, snapshot, lock, intervalo_val):
    """
    Proceso analizador de Señales de los procesos (/proc/<pid>/status).
    """
    print("[Analizador Señales] Iniciado y listo.")
    
    while True:
        # 1. Recibimos la lista de PIDs del Recolector
        pids = cola_pids.get()
        while not cola_pids.empty():
            try:
                pids = cola_pids.get_nowait()
            except:
                break
        
        datos_senales = {}
        
        # 2. Leemos las máscaras de señales para cada proceso
        for pid in pids:
            status = leer_status_proceso(pid)
            if not status:
                continue
                
            sig_pnd_hex = status.get('SigPnd', '0000000000000000')
            shd_pnd_hex = status.get('ShdPnd', '0000000000000000')
            sig_blk_hex = status.get('SigBlk', '0000000000000000')
            sig_ign_hex = status.get('SigIgn', '0000000000000000')
            sig_cgt_hex = status.get('SigCgt', '0000000000000000')
            
            datos_senales[pid] = {
                "pid": pid,
                "hex": {
                    "pending": sig_pnd_hex,
                    "shared_pending": shd_pnd_hex,
                    "blocked": sig_blk_hex,
                    "ignored": sig_ign_hex,
                    "caught": sig_cgt_hex
                },
                "decodificado": {
                    "pending_num": decodificar_mascara_senales(sig_pnd_hex),
                    "blocked_num": decodificar_mascara_senales(sig_blk_hex),
                    "ignored_num": decodificar_mascara_senales(sig_ign_hex),
                    "caught_num": decodificar_mascara_senales(sig_cgt_hex),
                    "pending_nom": nombres_desde_mascara(sig_pnd_hex),
                    "blocked_nom": nombres_desde_mascara(sig_blk_hex),
                    "ignored_nom": nombres_desde_mascara(sig_ign_hex),
                    "caught_nom": nombres_desde_mascara(sig_cgt_hex)
                }
            }
            
        # 3. Guardamos en el snapshot compartido de forma segura
        with lock:
            snapshot["senales"] = datos_senales
            
        time.sleep(intervalo_val.value)