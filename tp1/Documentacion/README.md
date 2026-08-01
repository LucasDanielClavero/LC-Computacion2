1. **Descripción general**
Este Monitor nos permite observar multiples vistas de la informacion de los procesos obteniendo dicha informacion directamente del directorio Proc

2. **Diagrama de arquitectura**
La arquitectura inicia por el archivo procfs.py, este archivo contiene todas las funciones necesarias para leer los datos del directorio proc, los analizadores importaran y utilizaran estas funciones para poder leer aquellos datos del directorio proc que necesiten, hablando de la informacion de proc el recolector es el encargado de extraer dicha informacion constantemente y enviarla a las colas de cada analizador para que ellos usen lo que necesiten para posteriormente darle un formato y plasmarla en la snapshot global que la TUI (la interfaz de usuario) empleara para mostrarnos los distintos datos de cada proceso del sistema

4. **Conceptos del curso aplicados**
-Queue: para evitar condiciones de carrera implemente el uso de multiples queue para enviar de forma individual a cada analizador los datos de proc 

-Terminate Y Join: al pasar a la etapa de finalizacion del archivo main.py, secuencialmente procede a primero terminar los procesos hijos con terminate (asi no quedan proceso huerfanos) y posteriormente aplica Join sobre todos para evitar que queden procesos zombies

-Manager: se implemento un manager para que todos los analizadores puedan enviar su informacion a una snapshot global y asi poder unir los datos de todos los analizadores en tiempo real

-Multiprocessing: aplicamos multiprocessing para poder tener paralelismo real, debido a que en phyton si usamos multiples hilos hay una limitacion que no nos permite ocupar varios nucleos a la vez (si no me equivoco se llama gild esa limitacion)

5. **Limitaciones conocidas**
-tengo que terminar de definir los signal

-aveces cuando se mantiene oprimido el boton para deslizar en la lista de procesos se traba y tarda un tiempo en reaccionar, hay que bajar poco a poco

6. **Cómo correr y testear**
## 🚀 Instrucciones de Ejecución
Para clonar y ejecutar la aplicación interactiva TUI en un solo comando:

bash
docker compose run --rm --build monitor

9. **Lo que aprendiste**

La verdad es que recien este año empece a usar linux y me costaba mucho adaptarme pero este tp me mostro que es realmente muy comodo, la informacion esta al alcance y es genial poder ver como interactuan los procesos en tiempo real, descubri que el kernel de linux (me imagino que igual aplica a cualquier kernel) es un proceso sumamente robusto, que comunicar datos entre multiples procesos es algo que esta al alcance de cualquiera si se hace con orden.

Descubri tambien que la IA es una excelente herramienta para aprender a la vez que se resuelve un problema, tiene sus limitacion pero es una genialidad poder ver de forma secuencial un tema teorico y luego verlo plasmado en el codigo de tu TP, eso ayuda a entender cada parte del codigo de tu proyecto aunque no lo hayamos escrito y nos permite poder tomar decisiones de diseño a la vez que aprendemos.

Algo que me sorprendio es lo mucho que se puede hacer con pocas librerias, la libreria OS tiene un monton de herramientas muy utiles, ahora entiendo porque por lo general cuando le pido a la IA generarme un codigo casi siempre la importa, tambien el saber que python tiene limitaciones al usar multiples hilos (no tiene paralelismo real) es algo muy importante a tener en cuenta cuando se realizan programas pesados que necesitan mucho procesador

Por ultimo este tp me dio una nocion nueva de las velocidades que maneja una computadora, todo este analisis de datos que hace nuestro codigo es posible porque extraemos datos de la ram, sin embargo si quisieramos hacer esto con el disco duro seria bastante mas complicado debido a que su tiempo de demora es muchismo mayor, cada parte del hardware tiene sus propial leyes y esta muy bueno saber eso


 