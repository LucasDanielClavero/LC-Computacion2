# Clase 18: De yield a asyncio

## Introducción: pausar una función

La clase anterior terminó con un bucle que esperaba eventos y despachaba a un callback. Funcionaba, pero tenía un costo que señalamos al pasar: el flujo del programa quedaba **partido en pedazos**.

Una conversación de tres pasos con un cliente —leer el pedido, consultar algo, responder— se convertía en tres funciones separadas, con el estado viajando a mano entre ellas y sin un `try` que abarcara la secuencia. En JavaScript le pusieron nombre a esa incomodidad: *callback hell*.

Lo que uno querría escribir es esto:

```python
datos = leer(conn)
resultado = consultar(datos)
escribir(conn, resultado)
```

Tres líneas, de arriba abajo, con variables locales que sobreviven y errores que se capturan normalmente. El problema es que cada una de esas llamadas bloquea, y si bloquea, el hilo no puede atender a nadie más.

**La pregunta de esta clase es si se puede tener las dos cosas**: código que se lee lineal, pero que en las esperas cede el control a otra tarea.

La respuesta es que sí, y el mecanismo ya lo tenían en la mano sin saberlo. Una función que se suspende en el medio, recuerda dónde iba, y puede reanudarse después es exactamente lo que vieron en el bloque 0: **un generador**.

Vamos a construir un event loop con generadores, y recién después vamos a ver `async` y `await` — que no son magia sino azúcar sintáctica sobre lo que habremos construido.

> **Nota:** los archivos `scheduler.py`, `puente.py` y `comparar.py` acompañan la clase.

---

## Un generador se suspende y recuerda

Repaso rápido de lo que ya vieron. Una función normal corre de principio a fin y muere:

```python
def contar():
    return [1, 2, 3]        # calcula todo y devuelve
```

Un generador, en cambio, **se detiene en cada `yield` y conserva su estado**:

```python
def contar():
    print('arranco')
    yield 1
    print('sigo')
    yield 2
    print('termino')

g = contar()
next(g)        # 'arranco'  -> devuelve 1, y se detiene
next(g)        # 'sigo'     -> devuelve 2, y se detiene
```

Entre un `next()` y el siguiente, el generador está **congelado**: sus variables locales siguen vivas, y sabe exactamente en qué línea retomar. Eso no lo hace una función común.

Fijate cómo se parece a lo que necesitamos. Una tarea que puede suspenderse en medio de una operación lenta, dejar que otro corra, y después continuar donde iba, sin perder nada.

---

## Y también recibe: `send()`

Lo que convierte a un generador en algo más que un iterador es que `yield` funciona **en las dos direcciones**. Además de producir un valor, puede recibir uno:

```python
def acumulador():
    total = 0
    while True:
        n = yield total        # produce total, y RECIBE el próximo n
        total += n

a = acumulador()
next(a)                        # arrancarlo hasta el primer yield
print(a.send(10))              # 10
print(a.send(5))               # 15
```

Ese `next(a)` inicial es obligatorio: un generador recién creado no ejecutó ni una línea, así que hay que llevarlo hasta el primer `yield` antes de poder mandarle algo. Si intentás `send()` de entrada, Python lanza `TypeError`.

Con `send()`, el generador deja de ser un productor de valores y pasa a ser **una tarea que se pausa, recibe un dato del exterior, y continúa**.

Ahí está todo lo que hace falta para un event loop. Falta armarlo.

---

## Un scheduler cooperativo en veinte líneas

Si cada tarea es un generador que cede el control con `yield`, alguien tiene que decidir a cuál reanudar. Ese alguien es el **scheduler**, y se escribe así:

```python
from collections import deque

def tarea(nombre, pasos):
    for i in range(1, pasos + 1):
        print(f'  [{nombre}] paso {i}/{pasos}')
        yield                          # me suspendo y cedo el control

def scheduler(tareas):
    pendientes = deque(tareas)
    while pendientes:
        t = pendientes.popleft()       # tomo la primera
        try:
            next(t)                    # la reanudo hasta su próximo yield
            pendientes.append(t)       # no terminó: al final de la cola
        except StopIteration:
            pass                       # terminó: la dejo ir

scheduler([tarea('A', 3), tarea('B', 2), tarea('C', 4)])
```

La salida:

```
  [A] paso 1/3
  [B] paso 1/2
  [C] paso 1/4
  [A] paso 2/3
  [B] paso 2/2
  [C] paso 2/4
  [A] paso 3/3
  [C] paso 3/4
  [C] paso 4/4
```

**Tres tareas avanzando de forma intercalada, en un solo hilo, sin threads.** Eso es concurrencia cooperativa, y lo acabás de implementar en veinte líneas.

Vale la pena detenerse en tres cosas.

**`StopIteration` es cómo termina una tarea.** Cuando el generador se queda sin código, Python lanza esa excepción y el scheduler la usa como señal de "esta ya está, no la vuelvo a encolar".

**El cambio de contexto es voluntario.** El scheduler no interrumpe a nadie: cada tarea decide cuándo ceder, escribiendo `yield`. Por eso se llama *cooperativa*, y es lo opuesto a los threads del sistema operativo, que el scheduler del kernel interrumpe cuando se le da la gana.

**Y de ahí sale la regla de oro**, la misma que vimos en la clase 17: si una tarea nunca cede —porque se puso a calcular durante dos segundos, o llamó a algo bloqueante— **todas las demás quedan congeladas**. En threads eso no pasaba porque el kernel repartía el tiempo por vos. Acá la cooperación es obligación de quien escribe la tarea.

### Esperar sin bloquear

Nuestro scheduler intercala, pero no sabe esperar. Agreguémosle tiempo: una tarea que quiere dormir cede el control informando **hasta cuándo** no vale la pena reanudarla.

```python
import time
from collections import deque

def dormir(segundos):
    """Cede el control indicando cuándo quiere volver."""
    yield time.monotonic() + segundos

def tarea(nombre, veces):
    for i in range(veces):
        print(f'  [{nombre}] {i}')
        yield from dormir(0.1)          # delega en otro generador

def scheduler(tareas):
    pendientes = deque((0, t) for t in tareas)      # (cuándo, tarea)
    while pendientes:
        despertar, t = pendientes.popleft()
        ahora = time.monotonic()
        if ahora < despertar:                        # todavía no le toca
            pendientes.append((despertar, t))
            continue
        try:
            cuando = next(t)                         # la tarea dice cuándo volver
            pendientes.append((cuando or 0, t))
        except StopIteration:
            pass
```

Dos cosas nuevas ahí.

**`yield from`** delega en otro generador: `tarea` no sabe cómo dormir, le pasa el control a `dormir` y los `yield` de adentro suben hasta el scheduler. Eso permite componer tareas a partir de piezas más chicas, igual que se componen funciones.

**El scheduler ahora entiende tiempo.** La tarea no dice "dormí por mí"; dice "no me reanudes hasta este instante". El scheduler decide, y mientras tanto corre a otros.

Ese bucle es, en esencia, lo que hace asyncio. Un asyncio real además usa `select`/`epoll` para dormir hasta que haya datos en vez de girar en vacío —lo que vimos en la clase 17— y tiene manejo de errores, cancelación y prioridades. Pero la idea es exactamente esta.

---

## El problema: `yield from` en todas partes

Este modelo funcionaba, y de hecho así se escribía asyncio antes de 2015:

```python
@asyncio.coroutine
def obtener_datos():
    conn = yield from abrir_conexion()
    datos = yield from leer(conn)
    return datos
```

Tiene dos problemas serios.

**Es ambiguo.** `yield from` significa dos cosas distintas según el contexto: iterar sobre un generador común, o suspender una tarea esperando un resultado. Leyendo el código no se distingue.

**Es fácil olvidarse.** Si escribís `datos = leer(conn)` sin el `yield from`, no falla: `datos` queda siendo un objeto generador que nunca se ejecutó. El bug aparece más tarde y lejos.

Python resolvió esto en la versión 3.5 (PEP 492) dándole **sintaxis propia** a la idea.

---

## `async` y `await`: la misma idea con nombre propio

```python
async def obtener_datos():
    conn = await abrir_conexion()
    datos = await leer(conn)
    return datos
```

La traducción es directa:

| Antes | Ahora | Qué significa |
|-------|-------|---------------|
| `def` + `yield from` | `async def` | Esta función se puede suspender |
| `yield from algo` | `await algo` | Suspendeme acá hasta que `algo` termine |

`async def` no crea un generador sino una **corrutina**, que es un objeto distinto a nivel de tipo. Eso resuelve la ambigüedad: el intérprete sabe cuál es cuál, y olvidarse el `await` ahora produce un aviso.

### La prueba de que es el mismo mecanismo

No hace falta creerlo: se puede verificar. Una corrutina tiene `.send()`, igual que un generador:

```python
async def saludar():
    return 42

c = saludar()
print(type(c).__name__)        # coroutine
print(hasattr(c, 'send'))      # True

try:
    c.send(None)               # arrancarla, como con next()
except StopIteration as e:
    print(e.value)             # 42  <- así devuelve su resultado
```

Ahí está todo el truco a la vista. `c.send(None)` la arranca; cuando termina, lanza `StopIteration` y el valor de retorno viaja en `e.value` —exactamente el mecanismo que usó nuestro scheduler para detectar tareas terminadas.

Cuando escribís `await algo`, por debajo ocurre un `send()` que suspende tu corrutina y le pasa el control al event loop. Y cuando el loop tiene la respuesta, hace otro `send()` con el resultado, que aparece como valor de la expresión `await`.

**`async`/`await` es azúcar sintáctica sobre generadores con `send()`.** El azúcar es valioso —hace el código legible y evita bugs— pero no hay nada abajo que no hayamos construido en esta clase.

---

## Lo mismo, con asyncio de verdad

Nuestro scheduler intercalado, escrito con la biblioteca:

```python
import asyncio

async def tarea(nombre, veces):
    for i in range(veces):
        print(f'  [{nombre}] {i}')
        await asyncio.sleep(0.1)          # cede el control

async def main():
    await asyncio.gather(
        tarea('A', 3),
        tarea('B', 2),
        tarea('C', 4),
    )

asyncio.run(main())
```

Las piezas, y su equivalente en lo que construimos:

| asyncio | Nuestro scheduler |
|---------|-------------------|
| `async def` | `def` con `yield` adentro |
| `await asyncio.sleep(n)` | `yield from dormir(n)` |
| `asyncio.gather(...)` | encolar varias tareas |
| `asyncio.run(main())` | llamar a `scheduler(...)` |

`asyncio.run()` crea el event loop, corre la corrutina hasta que termine, y cierra todo. Es el punto de entrada, y va **una sola vez** en tu programa.

`gather()` lanza varias corrutinas y espera a que todas terminen. Es lo que produce el intercalado.

### `asyncio.sleep` contra `time.sleep`

Este es el error número uno de quien arranca con asyncio, y ahora tienen las herramientas para entender por qué:

```python
await asyncio.sleep(1)     # cede el control: otros corren durante ese segundo
time.sleep(1)              # NO cede: congela el event loop entero
```

`time.sleep()` es una llamada bloqueante común: detiene el hilo. Y como en asyncio hay **un solo hilo**, detiene a todas las tareas. En nuestro scheduler sería una tarea que se queda calculando sin llegar nunca a su `yield`.

La regla general, que es la de la clase 17 con otra ropa: **nada bloqueante adentro de una corrutina**. Ni `time.sleep()`, ni `requests.get()`, ni una consulta a base de datos sincrónica, ni un cálculo largo. Todo eso hay que reemplazarlo por su versión asíncrona, o sacarlo del loop con un executor —algo que vamos a ver en la clase 22.

---

## Cuándo sirve, y cuánto

Asyncio no hace tu programa más rápido por arte de magia. Sirve cuando el programa **pasa el tiempo esperando**, no calculando.

Con tres tareas que esperan un segundo cada una:

| Forma | Tiempo |
|-------|--------|
| Secuencial (`time.sleep` en fila) | ~3 s |
| Con `asyncio.gather` | ~1 s |

Las tres esperas ocurren en paralelo porque esperar no consume CPU: mientras una tarea está suspendida, el loop corre a las otras.

Pero si en vez de esperar las tareas **calculan** un segundo cada una, asyncio no cambia nada: siguen siendo ~3 s, porque hay un solo hilo y el trabajo es real. Peor aún, la primera tarea no cede hasta terminar, así que ni siquiera se intercalan.

Es la misma distinción de la clase 10 con el GIL: **I/O-bound contra CPU-bound**. Asyncio es excelente para lo primero e inútil para lo segundo.

| Situación | Herramienta |
|-----------|-------------|
| Muchas esperas de red o disco | asyncio |
| Cálculo pesado | procesos (clase 9) |
| Pocas tareas, código simple | threads (clase 10) |
| Miles de conexiones | asyncio |

---

## Un adelanto: lo que van a ver en FastAPI

La clase que viene vamos a usar FastAPI, y van a encontrar endpoints escritos así:

```python
@app.get('/tareas')
async def listar_tareas():
    ...
```

Ese `async def` es exactamente lo de esta clase: una corrutina que el framework corre en un event loop. FastAPI usa asyncio por debajo, y por eso puede atender muchas peticiones concurrentes con pocos procesos.

Con lo de hoy ya saben leer eso sin que parezca magia. Lo que todavía no vimos es cómo se hace I/O de red asíncrono de verdad —abrir conexiones, leer, escribir— y eso es la clase 20.

---

## Conceptos clave

1. **Un generador se suspende y recuerda**: sus locales siguen vivas entre un `next()` y el siguiente.
2. **`send()` hace que también reciba**: el generador pasa de productor a tarea suspendible.
3. **El primer `next()` es obligatorio** antes de un `send()`, o hay `TypeError`.
4. **Un scheduler cooperativo son veinte líneas**: una cola de generadores y un `next()` por turno.
5. **`StopIteration` señala que la tarea terminó**, y su `.value` trae el resultado.
6. **El cambio de contexto es voluntario**: quien no cede, congela a todos.
7. **`yield from` delega en otro generador** y permite componer tareas.
8. **`async def` es `def` con `yield from`, y `await` es `yield from`**, con sintaxis propia desde Python 3.5.
9. **Una corrutina tiene `.send()`**: se puede verificar que es el mismo mecanismo.
10. **`asyncio.run()` va una sola vez**; `gather()` lanza varias corrutinas juntas.
11. **`time.sleep()` en una corrutina es un bug**: bloquea el hilo único.
12. **Asyncio sirve para I/O-bound, no para CPU-bound**: es la distinción de la clase 10 otra vez.

---

## Preparación para la próxima clase

En la **clase 19 (HTTP + FastAPI)** subimos de capa: del transporte al protocolo de aplicación que sostiene la web. Vamos a hablar HTTP a mano con `nc` —como en la clase 12—, ver `http.server` (que es `socketserver` con un handler que habla HTTP) y después construir una API con FastAPI.

Es también la clase donde se entrega el **enunciado del TP2**.

Para llegar preparado:

- Corré `scheduler.py` y seguí el orden de ejecución línea por línea.
- Convencete de que una corrutina tiene `.send()`: el ejemplo está en `puente.py`.

---

## Referencias

- [PEP 492](https://peps.python.org/pep-0492/) - el documento que introdujo `async`/`await`, con la justificación de por qué `yield from` no alcanzaba
- [PEP 342](https://peps.python.org/pep-0342/) - el que agregó `send()` a los generadores, en 2005
- [`asyncio`](https://docs.python.org/3/library/asyncio.html) - documentación oficial
- [How the heck does async/await work in Python?](https://snarky.ca/how-the-heck-does-async-await-work-in-python-3-5/) - Brett Cannon, el recorrido largo de generadores a corrutinas

---

*Computación II - 2026 - Clase 18*
