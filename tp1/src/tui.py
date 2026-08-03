import os
import time
import re
import senales
from blessed import Terminal
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

term = Terminal()
console = Console()

def parsear_kb_a_mb(valor):
    """Convierte strings como '318908 kB' o números a MB floats."""
    if not valor:
        return 0.0
    try:
        if isinstance(valor, (int, float)):
            return float(valor) / 1024.0

        val_str = str(valor).lower().strip()
        num_match = re.search(r"[-+]?\d*\.\d+|\d+", val_str)
        if num_match:
            num = float(num_match.group())
            if "kb" in val_str or num > 10000:
                return num / 1024.0
            elif "gb" in val_str:
                return num * 1024.0
            elif "bytes" in val_str:
                return num / (1024.0 * 1024.0)
            return num
    except (ValueError, TypeError):
        pass
    return 0.0


def extraer_ejemplo_fd(info):
    """Extrae el destino del primer descriptor de archivo abierto."""
    if not isinstance(info, dict):
        return "(Sin FDs)"
        
    descriptores = info.get("descriptores") or info.get("fds") or info.get("lista_fds") or []
    
    if isinstance(descriptores, list) and len(descriptores) > 0:
        elem = descriptores[0]
        if isinstance(elem, dict):
            fd_num = elem.get("fd", "?")
            dest = elem.get("destino") or elem.get("target") or elem.get("path") or "desconocido"
            return f"FD {fd_num} -> {dest}"
        else:
            return f"FD {elem}"
            
    return "(Sin FDs / Acceso Restringido)"


def construir_tabla(vista, snapshot_completo, indice_sel, pid_pinned, filtro_cmd, filtro_user, orden_col):
    
    # --- VISTA 7: SISTEMA GLOBAL (No itera sobre PIDs) ---
    if vista in ["7", "g"]:
        table = Table(title="[bold green]Vista 7: Sistema Global[/bold green]", expand=True)
        table.add_column("Métrica del Sistema", style="cyan", justify="right")
        table.add_column("Valor Actual / Información", style="bold white")
        
        sys_data = snapshot_completo.get("sistema", {})
        
        cpu = sys_data.get("cpu_global_pct", 0.0)
        load = " ".join(sys_data.get("loadavg", ["0.00", "0.00", "0.00"]))
        up_s = sys_data.get("uptime", 0.0)
        horas = int(up_s // 3600)
        mins = int((up_s % 3600) // 60)
        
        mem = sys_data.get("memoria", {})
        mt = mem.get("MemTotal", 0) / 1024
        ma = mem.get("MemAvailable", 0) / 1024
        st = mem.get("SwapTotal", 0) / 1024
        sf = mem.get("SwapFree", 0) / 1024
        
        table.add_row("CPU Global", f"{cpu}% de Uso Total")
        table.add_row("Load Average (1m, 5m, 15m)", load)
        table.add_row("Tiempo de Uptime", f"{horas}h {mins}m")
        table.add_row("Memoria RAM", f"Total: {mt:.1f} MB | Disponible: {ma:.1f} MB")
        table.add_row("Memoria Swap", f"Total: {st:.1f} MB | Libre: {sf:.1f} MB")
        
        # Devolvemos la tabla directamente (no hay items seleccionables)
        return table, [], 0
    # -----------------------------------------------------

    mapa_claves = {
        "1": "resumen", "2": "memoria", "3": "fds", 
        "4": "threads", "5": "senales", "6": "scheduling"
    }
    clave_snap = mapa_claves.get(vista, "resumen")
    datos = dict(snapshot_completo.get(clave_snap, {}))
    datos_resumen = dict(snapshot_completo.get("resumen", {}))
    datos_memoria = dict(snapshot_completo.get("memoria", {}))

    # 1. Filtrado
    items = []
    for pid, info in datos.items():
        pid_str = str(pid)
        if not pid_str.isdigit():
            continue

        if not isinstance(info, dict):
            info = {"val": info}

        info_res = datos_resumen.get(pid_str, datos_resumen.get(int(pid_str), {}))
        cmd = str(info.get("cmdline") or info.get("name") or info_res.get("cmdline") or info_res.get("name") or "").lower()
        user = str(info.get("user") or info_res.get("user") or "").lower()
        
        if filtro_cmd and filtro_cmd.lower() not in cmd:
            continue
        if filtro_user and filtro_user.lower() not in user:
            continue
            
        items.append((pid_str, info, info_res))

    # 2. Ordenamiento Global
    if orden_col == "RSS":
        def obtener_rss(item):
            p_id, inf, _ = item
            inf_mem = datos_memoria.get(p_id, datos_memoria.get(int(p_id), inf))
            return parsear_kb_a_mb(inf_mem.get("vmrss"))
        items.sort(key=obtener_rss, reverse=True)

    elif orden_col == "CPU":
        def obtener_cpu(item):
            _, inf, inf_res = item
            val = inf.get("run_time_ms") or inf_res.get("run_time_ms") or inf.get("cpu_ms") or 0
            try:
                return float(val)
            except (ValueError, TypeError):
                return 0.0
        items.sort(key=obtener_cpu, reverse=True)

    else:
        items.sort(key=lambda x: int(x[0]))

    # Pinned PID
    if pid_pinned is not None:
        items_pinned = [item for item in items if item[0] == str(pid_pinned)]
        items_resto = [item for item in items if item[0] != str(pid_pinned)]
        items = items_pinned + items_resto

    titulos = {
        "1": "Vista 1: Resumen General",
        "2": "Vista 2: Uso de Memoria",
        "3": "Vista 3: Descriptores de Archivo (FDs)",
        "4": "Vista 4: Threads (LWPs)",
        "5": "Vista 5: Máscaras de Señales",
        "6": "Vista 6: Scheduling y Context Switches"
    }

    table = Table(title=f"[bold green]{titulos.get(vista, 'Vista')}[/bold green]", expand=True)
    table.add_column("S", width=2, justify="center")
    table.add_column("PID", style="cyan", justify="right")

    if vista in ["1", "r"]:
        table.add_column("Usuario", style="magenta")
        table.add_column("Estado", style="bold yellow")
        table.add_column("Comando", style="white")
    elif vista in ["2", "m"]:
        table.add_column("VmSize (MB)", justify="right")
        table.add_column("VmRSS (MB)", justify="right", style="bold green")
        table.add_column("VmSwap (MB)", justify="right", style="red")
    elif vista in ["3", "f"]:
        table.add_column("Cant. FDs", justify="right")
        table.add_column("Ejemplo FD Abierto", style="dim white")
    elif vista in ["4", "t"]:
        table.add_column("Cant. Hilos", justify="right")
        table.add_column("Detalle LWP (TID, Est, CPU%)", style="dim white")
    elif vista in ["5", "s"]:
        table.add_column("Ignoradas (Hex)", style="yellow")
        table.add_column("Capturadas (Hex)", style="green")
    elif vista in ["6", "p"]:
        table.add_column("Prio/Nice/RT", justify="center")
        table.add_column("Policy", style="magenta", justify="center")
        table.add_column("CPU Affinity", justify="center")
        table.add_column("uTime/sTime", justify="right")
        table.add_column("Vol/NonVol Ctx", justify="right")
        table.add_column("SID/PGID", justify="right")

    max_filas = 16
    inicio = max(0, min(indice_sel - max_filas // 2, max(0, len(items) - max_filas)))
    fin = inicio + max_filas

    for idx, (pid, info, info_res) in enumerate(items[inicio:fin], start=inicio):
        es_sel = (idx == indice_sel)
        es_pin = (pid == str(pid_pinned))

        prefix = "📌" if es_pin else (">" if es_sel else " ")
        estilo_fila = "on blue" if es_sel else None

        if vista in ["1", "r"]:
            cmd = info.get("cmdline") or info.get("name") or "[Kernel Thread]"
            usr = info.get("user") or info.get("usuario") or "root"
            est = info.get("state") or info.get("estado") or info.get("status") or "R"
            table.add_row(prefix, pid, str(usr), str(est), str(cmd)[:55], style=estilo_fila)

        elif vista in ["2", "m"]:
            vmsize = parsear_kb_a_mb(info.get("vmsize"))
            vmrss = parsear_kb_a_mb(info.get("vmrss"))
            vmswap = parsear_kb_a_mb(info.get("vmswap"))
            table.add_row(prefix, pid, f"{vmsize:.2f}", f"{vmrss:.2f}", f"{vmswap:.2f}", style=estilo_fila)

        elif vista in ["3", "f"]:
            cant_fds = info.get("cant_fds") or info.get("fds_count") or info.get("count") or 0
            ejemplo = extraer_ejemplo_fd(info)
            table.add_row(prefix, pid, str(cant_fds), str(ejemplo)[:60], style=estilo_fila)

        elif vista in ["4", "t"]:
            cant_hilos = info.get("cant_hilos", 0)
            detalles = info.get("detalle_hilos", [])
            if detalles:
                # Mostramos métricas del primer hilo como resumen
                ejemplo = f"TID {detalles[0]['tid']} ({detalles[0]['estado']}) CPU: {detalles[0]['cpu_porcentaje']}%"
            else:
                ejemplo = "(Sin hilos)"
            table.add_row(prefix, pid, str(cant_hilos), str(ejemplo)[:60], style=estilo_fila)

        elif vista in ["5", "s"]:
            hex_ign = info.get("hex", {}).get("ignored") or info.get("sig_ign") or "0000000000000000"
            hex_cgt = info.get("hex", {}).get("caught") or info.get("sig_cgt") or "0000000000000000"
            table.add_row(prefix, pid, str(hex_ign)[:16], str(hex_cgt)[:16], style=estilo_fila)

        elif vista in ["6", "p"]:
            # Obtenemos los nuevos datos que mandamos desde el analizador
            prio = info.get("priority", "?")
            nice = info.get("nice", "?")
            rt = info.get("rt_priority", "?")
            policy = info.get("policy", "?")
            affinity = str(info.get("cpu_affinity", "N/A"))
            utime = info.get("utime", 0)
            stime = info.get("stime", 0)
            v_ctx = info.get("voluntary_ctx", 0)
            nv_ctx = info.get("nonvoluntary_ctx", 0)
            sid = info.get("sid", "?")
            pgid = info.get("pgid", "?")
            
            # Agregamos la fila formateada
            table.add_row(
                prefix, 
                pid, 
                f"{prio}/{nice}/{rt}", 
                str(policy), 
                affinity, 
                f"{utime}/{stime}", 
                f"{v_ctx}/{nv_ctx}", 
                f"{sid}/{pgid}", 
                style=estilo_fila
            )
    return table, items, len(items)


def desplegar_tui(snapshot, lock):
    vista_actual = "1"
    indice_sel = 0
    pid_pinned = None
    filtro_cmd = ""
    filtro_user = ""
    ordenes = ["PID", "CPU", "RSS"]
    idx_orden = 0
    intervalo_refresco = 1.0
    mostrar_ayuda = False

    teclas_vistas = {
        '1': '1', 'r': '1',
        '2': '2', 'm': '2',
        '3': '3', 'f': '3',
        '4': '4', 't': '4',
        '5': '5', 's': '5',
        '6': '6', 'p': '6',
        '7': '7', 'g': '7'
    }

    with term.cbreak(), term.hidden_cursor():
        while True:

            senales.procesar_flags_senales(snapshot)
            if senales.FLAG_SHUTDOWN:
                break

            with lock:
                snapshot_copy = dict(snapshot)

            console.clear()

            if mostrar_ayuda:
                texto_ayuda = (
                    "=== TECLAS OBLIGATORIAS DE NAVEGACIÓN ===\n\n"
                    "1-7 / r,m,f,t,s,p,g: Cambiar Vista\n"
                    "↑ / ↓: Mover selección (Vistas 1-6)\n"
                    "Enter: Fijar / Desfijar PID (Pin)\n"
                    "/: Filtrar por Nombre de Comando\n"
                    "u: Filtrar por Usuario\n"
                    "c: Alternar Ordenamiento (PID -> CPU -> RSS)\n"
                    "+ / -: Ajustar velocidad de refresco\n"
                    "h / ?: Ocultar ayuda\n"
                    "q: Salir\n\n"
                    "Presione 'h' o '?' para cerrar."
                )
                console.print(Panel(Text(texto_ayuda, style="bold yellow"), title="AYUDA Y KEYBINDINGS", border_style="magenta"))
            else:
                tabla, items_filtrados, total_visibles = construir_tabla(
                    vista_actual, snapshot_copy, indice_sel, pid_pinned, filtro_cmd, filtro_user, ordenes[idx_orden]
                )

                pin_txt = f"Pinned: {pid_pinned}" if pid_pinned else "Pinned: Ninguno"
                f_cmd_txt = f"F.Cmd: '{filtro_cmd}'" if filtro_cmd else "F.Cmd: Off"
                f_usr_txt = f"F.User: '{filtro_user}'" if filtro_user else "F.User: Off"

                header_str = (
                    f"Vistas: [1/r]Res [2/m]Mem [3/f]FDs [4/t]Thr [5/s]Señ [6/p]Sch [7/g]Sis\n"
                    f"Orden: {ordenes[idx_orden]} | {pin_txt} | {f_cmd_txt} | {f_usr_txt} | Refresco: {intervalo_refresco:.1f}s\n"
                    f"Teclas: [↑/↓] Mover | [Enter] Pin | [/] F.Cmd | [u] F.User | [c] Orden | [+/-] Vel | [h] Ayuda | [q] Salir"
                )

                console.print(Panel(Text(header_str, style="cyan"), title="MONITOR PROC - TUI", border_style="bright_blue"))
                console.print(tabla)

            val = term.inkey(timeout=intervalo_refresco)

            if not val:
                continue

            char = val.lower()

            if char == 'q':
                break
            elif char in ['h', '?']:
                mostrar_ayuda = not mostrar_ayuda
            elif char in teclas_vistas:
                vista_actual = teclas_vistas[char]
                indice_sel = 0
            elif val.name == "KEY_UP":
                if indice_sel > 0:
                    indice_sel -= 1
            elif val.name == "KEY_DOWN":
                if indice_sel < total_visibles - 1:
                    indice_sel += 1
            elif val.name == "KEY_ENTER" or char in ['\n', '\r']:
                if total_visibles > 0 and indice_sel < len(items_filtrados):
                    pid_actual = items_filtrados[indice_sel][0]
                    if pid_pinned == pid_actual:
                        pid_pinned = None
                    else:
                        pid_pinned = pid_actual
            elif char == 'c':
                idx_orden = (idx_orden + 1) % len(ordenes)
            elif char in ['+', '=']:
                intervalo_refresco = max(0.2, intervalo_refresco - 0.2)
            elif char in ['-', '_']:
                intervalo_refresco = min(5.0, intervalo_refresco - 0.2)
            elif char == '/':
                with term.cooked():
                    console.print("\n[bold yellow]Filtro comando (Enter para aplicar / vacío borra):[/bold yellow]")
                    filtro_cmd = input("> ").strip()
                indice_sel = 0
            elif char == 'u':
                with term.cooked():
                    console.print("\n[bold magenta]Filtro usuario (Enter para aplicar / vacío borra):[/bold magenta]")
                    filtro_user = input("> ").strip()
                indice_sel = 0