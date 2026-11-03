"""
Pruebas automatizadas de la API (bonus de la consigna: tests, especialmente
de cancelacion).

Le pegan a la app de verdad via ASGI (httpx.ASGITransport), sin red: es el
mismo stack FastAPI -> gestor -> workers, y los timeouts de red nunca son
cuello de botella. Cada test levanta su propia instancia con la fixture
`api` y la apaga al final (eso tambien prueba el apagado ordenado en cada
uno, porque el lifespan corre apagar()).

Se corren con:
    python -m pytest tests/ -v
"""

import asyncio
import time

import httpx
import pytest

import api as modulo_api


@pytest.fixture
async def api(monkeypatch):
    """Una instancia de la app con 1 solo worker, para poder probar la cola."""
    import gestor
    monkeypatch.setattr(gestor, "NUM_WORKERS", 1)
    instance = modulo_api.app
    async with instance.router.lifespan_context(instance):
        transport = httpx.ASGITransport(app=instance)
        cliente = httpx.AsyncClient(
            transport=transport, base_url="http://test"
        )
        instance.state.cliente = cliente
        yield instance
        await cliente.aclose()


def post(api, payload):
    return api.state.cliente.post("/tareas", json=payload)


async def esperar_estado(api, id_tarea, estados, timeout=10):
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < timeout:
        tarea = (await api.state.cliente.get(f"/tareas/{id_tarea}")).json()
        if tarea["estado"] in estados:
            return tarea
        await asyncio.sleep(0.02)
    raise AssertionError(f"la tarea no llego a {estados} en {timeout}s")


# ------------------------------------------------------------------
# Funcionalidad basica y el POST inmediato
# ------------------------------------------------------------------

async def test_post_responde_201_y_al_toque(api):
    t0 = time.perf_counter()
    resp = await post(api, {"tipo": "esperar", "params": {"segundos": 3}})
    t_post = time.perf_counter() - t0

    assert resp.status_code == 201
    datos = resp.json()
    assert datos["estado"] == "pendiente"
    # El POST tiene que volver mucho antes de que termine la tarea (3 s)
    assert t_post < 1.0
    await esperar_estado(api, datos["id"], ("completada",))


async def test_ciclo_completo_listado_filtro_y_estadisticas(api):
    resp = await post(api, {"tipo": "esperar", "params": {"segundos": 0.05}})
    id_tarea = resp.json()["id"]
    await esperar_estado(api, id_tarea, ("completada",))

    listado = (await api.state.cliente.get("/tareas")).json()
    assert any(t["id"] == id_tarea for t in listado)

    filtrado = (await api.state.cliente.get(
        "/tareas", params={"estado": "completada"}
    )).json()
    assert filtrado and all(t["estado"] == "completada" for t in filtrado)
    assert not any(
        t["estado"] != "completada"
        for t in (await api.state.cliente.get("/tareas", params={"estado": "fallida"})).json()
    )

    estadisticas = (await api.state.cliente.get("/estadisticas")).json()
    assert estadisticas["tareas_totales"] >= 1
    assert estadisticas["totales_por_estado"]["completada"] >= 1
    # campos que la consigna pide (workers) + los que agregamos
    assert estadisticas["workers_totales"] == 1
    assert "tareas_en_cola" in estadisticas
    assert "aceptando_tareas" in estadisticas


async def test_resultado_de_descarga_y_hashear_por_executor(api):
    resp = await post(api, {"tipo": "hashear",
                            "params": {"texto": "hola", "iteraciones": 10}})
    tarea = await esperar_estado(api, resp.json()["id"], ("completada",))
    # sha256('hola').hex() tiene 64 hex: el calculo vino del pool de procesos
    assert len(tarea["resultado"]) == 64


async def test_validacion_del_tipo_y_de_los_params(api):
    resp = await post(api, {"tipo": "cocinar", "params": {}})
    assert resp.status_code == 400
    resp = await post(api, {"tipo": "esperar", "params": {}})
    assert resp.status_code == 400
    resp = await post(api, {"tipo": "hashear",
                            "params": {"texto": "a", "iteraciones": 0}})
    assert resp.status_code == 400
    # y un GET de tarea inexistente da 404
    resp = await api.state.cliente.get("/tareas/txkein")
    assert resp.status_code == 404


# ------------------------------------------------------------------
# Timeout y cancelacion (el corazon del bonus)
# ------------------------------------------------------------------

async def test_timeout_deja_la_tarea_fallida(api):
    resp = await post(api, {"tipo": "esperar", "params": {"segundos": 30},
                            "timeout_s": 0.3})
    tarea = await esperar_estado(api, resp.json()["id"], ("fallida",))
    assert "timeout" in tarea["error"].lower()


async def test_cancelar_en_ejecucion_es_inmediato(api):
    resp = await post(api, {"tipo": "esperar", "params": {"segundos": 30}})
    id_tarea = resp.json()["id"]
    await esperar_estado(api, id_tarea, ("ejecutando",))

    t0 = time.perf_counter()
    resp_del = await api.state.cliente.delete(f"/tareas/{id_tarea}")
    t_del = time.perf_counter() - t0
    assert resp_del.status_code == 200

    # La cancelacion no deja la corrutina colgada: cae casi al toque
    assert t_del < 1.0
    tarea = await esperar_estado(api, id_tarea, ("cancelada",))
    assert tarea["error"] is None
    # Y la API sigue atendiendo peticiones despues de cancelar
    assert (await api.state.cliente.get("/estadisticas")).status_code == 200


async def test_cancelar_pendiente_no_arranca_nunca(api):
    # 1 worker: el primero ocupa al worker, los demas quedan pendientes
    id_ocupando = (await post(api, {"tipo": "esperar", "params": {"segundos": 1.5}})).json()["id"]
    ids_pendientes = []
    for _ in range(2):
        ids_pendientes.append(
            (await post(api, {"tipo": "esperar", "params": {"segundos": 5}})).json()["id"]
        )

    await esperar_estado(api, id_ocupando, ("completada", "ejecutando"))
    # Cancelo la primera pendiente antes de que arranque
    resp = await api.state.cliente.delete(f"/tareas/{ids_pendientes[0]}")
    assert resp.status_code == 200

    await esperar_estado(api, ids_pendientes[1], ("completada",), timeout=15)
    cancelada = (await api.state.cliente.get(f"/tareas/{ids_pendientes[0]}")).json()
    assert cancelada["estado"] == "cancelada"
    assert cancelada["resultado"] is None


async def test_delete_sobre_tarea_terminada_da_409(api):
    resp = await post(api, {"tipo": "esperar", "params": {"segundos": 0.05}})
    id_tarea = resp.json()["id"]
    await esperar_estado(api, id_tarea, ("completada",))

    de_nuevo = await api.state.cliente.delete(f"/tareas/{id_tarea}")
    assert de_nuevo.status_code == 409
    # una inexistente sigue siendo 404
    assert (await api.state.cliente.delete("/tareas/t9")).status_code == 404


# ------------------------------------------------------------------
# Backpressure y robustez
# ------------------------------------------------------------------

async def test_cola_llena_responde_503(api, monkeypatch):
    import gestor
    monkeypatch.setattr(gestor, "COLA_MAXSIZE", 2)

    # Re-creo el gestor para que la cola tome el nuevo maxsize
    await api.state.gestor.apagar()
    gestor_fresco = gestor.GestorTareas()
    api.state.gestor = gestor_fresco
    await gestor_fresco.iniciar()

    # 1 tarea corriendo + 2 pendientes (maxsize) -> la cuarta rechaza 503
    resp1 = await post(api, {"tipo": "esperar", "params": {"segundos": 2}})
    assert resp1.status_code == 201
    await esperar_estado(api, resp1.json()["id"], ("ejecutando",))
    resp2 = await post(api, {"tipo": "esperar", "params": {"segundos": 2}})
    resp3 = await post(api, {"tipo": "esperar", "params": {"segundos": 2}})
    resp4 = await post(api, {"tipo": "esperar", "params": {"segundos": 2}})
    assert resp2.status_code == 201
    assert resp3.status_code == 201
    assert resp4.status_code == 503


async def test_excepcion_de_tarea_deja_fallida_y_el_worker_sigue(api, monkeypatch):
    import gestor

    async def explotar(params):
        raise ValueError("boom a proposito")

    # El parche vale SOLO para la primera tarea: si quedara puesto, la
    # segunda tambien explotaria y el nunca llegaria a 'completada'.
    with monkeypatch.context() as m:
        m.setattr(gestor, "ejecutar_esperar", explotar)
        resp = await post(api, {"tipo": "esperar", "params": {"segundos": 0.05}})
        tarea = await esperar_estado(api, resp.json()["id"], ("fallida",))
        assert "boom a proposito" in tarea["error"]

    # El worker no murio: la tarea siguiente completa normalmente
    resp2 = await post(api, {"tipo": "esperar", "params": {"segundos": 0.05}})
    await esperar_estado(api, resp2.json()["id"], ("completada",))


async def test_apagado_ordenado_es_acotado_con_cola_cargada(api, monkeypatch):
    import gestor

    # Vuelco el proxy de la fixture (colas viejas) y armo una instancia
    # chica con limite de apagado corto para probar el techo del apagado.
    monkeypatch.setattr(gestor, "LIMITE_APAGADO", 0.5)
    await api.state.gestor.apagar()
    gestor_fresco = gestor.GestorTareas()
    api.state.gestor = gestor_fresco
    await gestor_fresco.iniciar()

    # 1 en ejecucion (30 s, no termina) + 5 pendientes: con el bug viejo,
    # estos pendientes se ejecutaban ANTES de la pastilla y el apagado
    # podia no volver nunca; ahora quedan cancelada y el apagado es acotado.
    ids = []
    for i in range(6):
        ids.append(
            (await post(api, {"tipo": "esperar", "params": {"segundos": 30},
                              "timeout_s": 30})).json()["id"]
        )
    await esperar_estado(api, ids[0], ("ejecutando",))

    t0 = time.perf_counter()
    await gestor_fresco.apagar()
    t_apagar = time.perf_counter() - t0

    # limite (0.5 s) + apagar colas: nunca puede irse a decenas de segundos
    assert t_apagar < 5.0, f"el apagado se estiro {t_apagar:.1f}s con cola cargada"
    # la en ejecucion quedo cancelada y TODAS las pendientes tambien
    registradas = gestor_fresco.registro
    assert registradas[ids[0]]["estado"] == "cancelada"
    for id_tarea in ids[1:]:
        assert registradas[id_tarea]["estado"] == "cancelada"
        assert registradas[id_tarea]["error"] == "cancelada durante el apagado"
