import os
import pwd

TICKS_POR_SEGUNDO = os.sysconf('SC_CLK_TCK')

def listar_pids():
    """Devuelve una lista de PIDs (enteros) activos en el sistema."""
    pids = []
    for elemento in os.listdir('/proc'):
        if elemento.isdigit():
            pids.append(int(elemento))
    return pids

def leer_status_proceso(pid):
    """
    Lee /proc/<pid>/status y devuelve un diccionario con los campos.
    Retorna None si el proceso ya no existe (FileNotFoundError).
    """
    ruta = f"/proc/{pid}/status"
    datos = {}
    try:
        with open(ruta, 'r') as f:
            for linea in f:
                if ':' in linea:
                    clave, valor = linea.split(':', 1)
                    datos[clave.strip()] = valor.strip()
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        # Manejamos los errores comunes al leer procesos del sistema
        return None
    return datos

def leer_cmdline(pid):
    """Lee /proc/<pid>/cmdline y devuelve el comando completo como string."""
    ruta = f"/proc/{pid}/cmdline"
    try:
        with open(ruta, 'r') as f:
            contenido = f.read()
            # Los argumentos en cmdline están separados por bytes nulos (\x00)
            comando = contenido.replace('\x00', ' ').strip()
            return comando if comando else "[sin cmdline]"
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return "[desconocido]"

def obtener_nombre_usuario(uid):
    """Traduce un UID numérico al nombre de usuario del sistema."""
    try:
        return pwd.getpwuid(int(uid)).pw_name
    except (KeyError, ValueError):
        return str(uid)

def leer_stat_proceso(pid):
    """
    Lee /proc/<pid>/stat.
    Devuelve un diccionario con el estado corto (R/S/D/T/Z) y los ticks de CPU (utime + stime).
    """
    ruta = f"/proc/{pid}/stat"
    try:
        with open(ruta, 'r') as f:
            contenido = f.read().strip()
            
            # El nombre del ejecutable en /proc/<pid>/stat está entre paréntesis (ej: (bash)).
            # Como el nombre puede contener espacios o paréntesis, buscamos el último ')'
            # para no romper el split por espacios.
            indice_cierre_parentesis = contenido.rfind(')')
            if indice_cierre_parentesis == -1:
                return None
                
            # Todo lo que está después del paréntesis son los campos numerados a partir del campo 3
            campos_restantes = contenido[indice_cierre_parentesis + 1:].strip().split()
            
            # campo 3 en el archivo original es el primer elemento de campos_restantes (índice 0)
            estado = campos_restantes[0] 
            
            # utime es el campo 14 y stime es el campo 15 en /proc/<pid>/stat.
            # Como recortamos los primeros 2 campos (PID y comm), en campos_restantes
            # corresponden a los índices 11 y 12.
            utime = int(campos_restantes[11])
            stime = int(campos_restantes[12])
            ticks_totales = utime + stime
            
            return {
                "estado": estado,
                "ticks": ticks_totales
            }
    except (FileNotFoundError, ProcessLookupError, PermissionError, IndexError, ValueError):
        return None

def leer_memoria_status(status):
    """
    Extrae las métricas de memoria desde el diccionario de /proc/<pid>/status.
    Devuelve un diccionario con VmSize, VmRSS, VmData, VmStk, VmExe, VmLib.
    """
    if not status:
        return None
        
    return {
        "vmsize": status.get('VmSize', '0 kB'),
        "vmrss": status.get('VmRSS', '0 kB'),
        "vmdata": status.get('VmData', '0 kB'),
        "vmstk": status.get('VmStk', '0 kB'),
        "vmexe": status.get('VmExe', '0 kB'),
        "vmlib": status.get('VmLib', '0 kB')
    }

def leer_maps_proceso(pid):
    """
    Lee /proc/<pid>/maps y devuelve una lista de diccionarios
    con el mapa de memoria del proceso.
    """
    ruta = f"/proc/{pid}/maps"
    regiones = []
    try:
        with open(ruta, 'r') as f:
            for linea in f:
                linea = linea.strip()
                if not linea:
                    continue
                # split con maxsplit=5 porque la ruta (pathname) puede contener espacios
                partes = linea.split(maxsplit=5)
                
                if len(partes) >= 5:
                    direccion = partes[0]
                    permisos = partes[1]
                    offset = partes[2]
                    device = partes[3]
                    inode = partes[4]
                    pathname = partes[5] if len(partes) == 6 else "[anon]"
                    
                    regiones.append({
                        "direccion": direccion,
                        "permisos": permisos,
                        "offset": offset,
                        "device": device,
                        "inode": inode,
                        "pathname": pathname
                    })
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return []
        
    return regiones   

def leer_limite_fds(pid):
    """Lee /proc/<pid>/limits y busca el 'Max open files'."""
    ruta = f"/proc/{pid}/limits"
    try:
        with open(ruta, 'r') as f:
            for linea in f:
                if 'Max open files' in linea:
                    partes = linea.split()
                    # La estructura típica es: Max open files <soft_limit> <hard_limit> <units>
                    return partes[3]  # Retorna el Soft Limit
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        pass
    return "N/A"

def leer_io_proceso(pid):
    """Lee /proc/<pid>/io y devuelve métricas de E/S."""
    ruta = f"/proc/{pid}/io"
    datos_io = {
        "rchar": "0", "wchar": "0", 
        "read_bytes": "0", "write_bytes": "0"
    }
    try:
        with open(ruta, 'r') as f:
            for linea in f:
                if ':' in linea:
                    clave, valor = linea.split(':', 1)
                    clave = clave.strip()
                    if clave in datos_io:
                        datos_io[clave] = valor.strip()
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        pass
    return datos_io

def leer_fds_proceso(pid):
    """
    Lista el directorio /proc/<pid>/fd y resuelve los links simbólicos
    junto con sus metadatos desde /proc/<pid>/fdinfo/<fd>.
    """
    ruta_fd = f"/proc/{pid}/fd"
    descriptores = []
    
    try:
        for fd_nombre in os.listdir(ruta_fd):
            ruta_link = f"{ruta_fd}/{fd_nombre}"
            
            # Resolvemos hacia dónde apunta el enlace simbólico
            try:
                destino = os.readlink(ruta_link)
            except (FileNotFoundError, OSError, PermissionError):
                destino = "[desconocido]"
                
            # Leemos pos y flags desde fdinfo si es posible
            pos = "0"
            flags = "0"
            ruta_fdinfo = f"/proc/{pid}/fdinfo/{fd_nombre}"
            try:
                with open(ruta_fdinfo, 'r') as f:
                    for linea in f:
                        if linea.startswith("pos:"):
                            pos = linea.split()[1]
                        elif linea.startswith("flags:"):
                            flags = linea.split()[1]
            except (FileNotFoundError, PermissionError):
                pass
                
            descriptores.append({
                "fd": fd_nombre,
                "destino": destino,
                "pos": pos,
                "flags": flags
            })
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return []
        
    return descriptores

def leer_schedstat_proceso(pid):
    """
    Lee /proc/<pid>/schedstat.
    Devuelve run_time, wait_time y pcount (o 'N/A' si no está disponible).
    """
    ruta = f"/proc/{pid}/schedstat"
    try:
        with open(ruta, 'r') as f:
            partes = f.read().strip().split()
            if len(partes) >= 3:
                return {
                    "run_time": int(partes[0]),
                    "wait_time": int(partes[1]),
                    "pcount": int(partes[2])
                }
    except (FileNotFoundError, ProcessLookupError, PermissionError, ValueError):
        pass
    return {"run_time": 0, "wait_time": 0, "pcount": 0}

def leer_scheduling_stat(pid):
    """
    Extrae las métricas obligatorias de scheduling desde /proc/<pid>/stat.
    Campos extraídos según man proc(5) considerando el offset por 'comm'.
    """
    ruta = f"/proc/{pid}/stat"
    datos = {
        "pgid": 0, "sid": 0, "utime": 0, "stime": 0, 
        "priority": 0, "nice": 0, "rt_priority": 0, "policy": 0, "policy_name": "UNKNOWN"
    }
    
    # Mapeo básico de políticas de Linux
    politicas = {
        0: "OTHER", 1: "FIFO", 2: "RR", 3: "BATCH", 5: "IDLE", 6: "DEADLINE"
    }
    
    try:
        with open(ruta, 'r') as f:
            contenido = f.read().strip()
            idx_cierre = contenido.rfind(')')
            if idx_cierre != -1:
                campos = contenido[idx_cierre + 1:].strip().split()
                
                # Desplazamiento: campo 3 es campos[0]
                datos["pgid"] = int(campos[2])       # Campo 5
                datos["sid"] = int(campos[3])        # Campo 6
                datos["utime"] = int(campos[11])     # Campo 14
                datos["stime"] = int(campos[12])     # Campo 15
                datos["priority"] = int(campos[15])  # Campo 18
                datos["nice"] = int(campos[16])      # Campo 19
                
                # Los campos 40 y 41 pueden no estar en versiones hiper viejas de kernel,
                # pero en Docker/Linux moderno siempre están.
                if len(campos) >= 39:
                    datos["rt_priority"] = int(campos[37]) # Campo 40
                    datos["policy"] = int(campos[38])      # Campo 41
                    datos["policy_name"] = politicas.get(datos["policy"], str(datos["policy"]))
                    
    except (FileNotFoundError, ProcessLookupError, PermissionError, IndexError, ValueError):
        pass
        
    return datos

def leer_hilos_task(pid):
    """
    Explora /proc/<pid>/task/ para listar todos los TIDs del proceso
    y obtener el estado individual de cada uno.
    """
    ruta_task = f"/proc/{pid}/task"
    hilos = []
    try:
        for tid_str in os.listdir(ruta_task):
            if tid_str.isdigit():
                tid = int(tid_str)
                # Leemos /proc/<pid>/task/<tid>/stat para el estado del hilo
                ruta_stat_tid = f"{ruta_task}/{tid_str}/stat"
                estado_hilo = "?"
                try:
                    with open(ruta_stat_tid, 'r') as f:
                        contenido = f.read().strip()
                        idx = contenido.rfind(')')
                        if idx != -1:
                            estado_hilo = contenido[idx + 1:].strip().split()[0]
                except (FileNotFoundError, PermissionError):
                    pass
                    
                hilos.append({
                    "tid": tid,
                    "estado": estado_hilo
                })
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return []
        
    return hilos

def decodificar_mascara_senales(hex_str):
    """
    Convierte una máscara hexadecimal (ej: '0000000000000004')
    en una lista de números de señales activas [3].
    """
    if not hex_str or hex_str == "N/A":
        return []
    try:
        val = int(hex_str, 16)
        senales = []
        for i in range(64):  # Linux maneja hasta 64 señales (32 estándar + 32 tiempo real)
            if (val >> i) & 1:
                senales.append(i + 1)  # La señal 1 es el bit 0
        return senales
    except ValueError:
        return []

def leer_cwd_proceso(pid):
    """Resuelve el enlace simbólico /proc/<pid>/cwd."""
    ruta = f"/proc/{pid}/cwd"
    try:
        return os.readlink(ruta)
    except (FileNotFoundError, OSError, PermissionError):
        return "[desconocido / sin permiso]"

def leer_environ_proceso(pid):
    """
    Lee /proc/<pid>/environ y devuelve un diccionario con las variables de entorno.
    """
    ruta = f"/proc/{pid}/environ"
    env_vars = {}
    try:
        with open(ruta, 'r') as f:
            contenido = f.read()
            # Las variables están separadas por bytes nulos (\x00)
            variables = contenido.split('\x00')
            for var in variables:
                if '=' in var:
                    clave, valor = var.split('=', 1)
                    env_vars[clave] = valor
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        pass
    return env_vars

def leer_detalles_hilo(pid, tid):
    """
    Lee stat, status y comm de un hilo (LWP) específico.
    Devuelve un diccionario con las métricas del hilo.
    """
    ruta_task = f"/proc/{pid}/task/{tid}"
    datos = {
        "tid": tid,
        "estado": "?",
        "ticks": 0,
        "comm": "[desconocido]",
        "vol_ctx": 0,
        "nonvol_ctx": 0
    }

    # 1. Leer nombre del hilo (comm)
    try:
        with open(f"{ruta_task}/comm", "r") as f:
            datos["comm"] = f.read().strip()
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        pass

    # 2. Leer estado y ticks de CPU (stat)
    try:
        with open(f"{ruta_task}/stat", "r") as f:
            contenido = f.read().strip()
            idx = contenido.rfind(')')
            if idx != -1:
                campos = contenido[idx + 1:].strip().split()
                # Campo 1 (estado), Campos 12 y 13 tras el ')' son utime y stime
                datos["estado"] = campos[0]
                datos["ticks"] = int(campos[11]) + int(campos[12])
    except (FileNotFoundError, ProcessLookupError, PermissionError, IndexError, ValueError):
        pass

    # 3. Leer context switches (status)
    try:
        with open(f"{ruta_task}/status", "r") as f:
            for linea in f:
                if linea.startswith("voluntary_ctxt_switches:"):
                    datos["vol_ctx"] = int(linea.split()[1])
                elif linea.startswith("nonvoluntary_ctxt_switches:"):
                    datos["nonvol_ctx"] = int(linea.split()[1])
    except (FileNotFoundError, ProcessLookupError, PermissionError, IndexError, ValueError):
        pass

    return datos

def leer_stat_global():
    """Lee el uso total de CPU del sistema y el tiempo de boot."""
    datos = {"total": 0, "idle": 0, "btime": 0}
    try:
        with open("/proc/stat", "r") as f:
            for linea in f:
                if linea.startswith("cpu "):
                    campos = linea.split()
                    valores = [int(x) for x in campos[1:]]
                    # idle (indice 3) + iowait (indice 4)
                    idle = valores[3] + (valores[4] if len(valores) > 4 else 0) 
                    total = sum(valores)
                    datos["total"] = total
                    datos["idle"] = idle
                elif linea.startswith("btime "):
                    datos["btime"] = int(linea.split()[1])
    except:
        pass
    return datos

def leer_loadavg():
    """Lee el promedio de carga del sistema (1, 5 y 15 min)."""
    try:
        with open("/proc/loadavg", "r") as f:
            return f.read().strip().split()[:3]
    except:
        return ["0.00", "0.00", "0.00"]

def leer_meminfo():
    """Lee la memoria global y la swap, incluyendo Buffers y Cached."""
    datos = {
        "MemTotal": 0, "MemFree": 0, "MemAvailable": 0, 
        "SwapTotal": 0, "SwapFree": 0, "Buffers": 0, "Cached": 0
    }
    try:
        with open("/proc/meminfo", "r") as f:
            for linea in f:
                partes = linea.split(":")
                if len(partes) == 2:
                    clave = partes[0].strip()
                    if clave in datos:
                        val = partes[1].replace("kB", "").strip()
                        datos[clave] = int(val)
    except:
        pass
    return datos

def leer_uptime():
    """Lee el tiempo de encendido del sistema en segundos."""
    try:
        with open("/proc/uptime", "r") as f:
            return float(f.read().split()[0])
    except:
        return 0.0

def leer_memoria_status(status):
    """
    Extrae las métricas de memoria desde el diccionario de /proc/<pid>/status.
    Ahora incluye VmHWM y VmSwap como pide la consigna.
    """
    if not status:
        return None
        
    return {
        "vmsize": status.get('VmSize', '0 kB'),
        "vmrss": status.get('VmRSS', '0 kB'),
        "vmdata": status.get('VmData', '0 kB'),
        "vmstk": status.get('VmStk', '0 kB'),
        "vmexe": status.get('VmExe', '0 kB'),
        "vmlib": status.get('VmLib', '0 kB'),
        "vmhwm": status.get('VmHWM', '0 kB'),   # Agregado
        "vmswap": status.get('VmSwap', '0 kB')  # Agregado
    }

def leer_page_faults(pid):
    """
    Lee /proc/<pid>/stat para obtener los Minor (campo 10) y Major (campo 12) page faults.
    """
    ruta = f"/proc/{pid}/stat"
    try:
        with open(ruta, 'r') as f:
            contenido = f.read().strip()
            idx_cierre = contenido.rfind(')')
            if idx_cierre != -1:
                campos = contenido[idx_cierre + 1:].strip().split()
                # En campos_restantes tras el ')':
                # El campo 3 (estado) es el índice 0
                # El campo 10 (minflt) es el índice 7
                # El campo 12 (majflt) es el índice 9
                return {
                    "minflt": int(campos[7]),
                    "majflt": int(campos[9])
                }
    except (FileNotFoundError, ProcessLookupError, PermissionError, IndexError, ValueError):
        pass
    return {"minflt": 0, "majflt": 0}

def agrupar_segmentos_memoria(regiones):
    """
    Recibe la lista devuelta por leer_maps_proceso() y agrupa 
    los tamaños en KB (text, data, heap, stack, shared).
    """
    agrupados = {"text": 0, "data": 0, "heap": 0, "stack": 0, "shared": 0}

    for reg in regiones:
        # Calcular el tamaño de la región (fin - inicio)
        try:
            inicio_hex, fin_hex = reg["direccion"].split("-")
            size_kb = (int(fin_hex, 16) - int(inicio_hex, 16)) // 1024
        except ValueError:
            size_kb = 0

        perm = reg["permisos"]
        path = reg["pathname"]

        # Agrupación según consigna
        if path == "[stack]":
            agrupados["stack"] += size_kb
        elif path == "[heap]":
            agrupados["heap"] += size_kb
        elif 's' in perm:
            agrupados["shared"] += size_kb
        elif 'x' in perm:  # Ejecutable suele ser código (text)
            agrupados["text"] += size_kb
        else:              # Resto suele ser data (inicializada/no inicializada)
            agrupados["data"] += size_kb

    return agrupados