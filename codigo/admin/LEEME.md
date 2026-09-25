# Módulo de administración

Herramienta para administrar el Asistente de Educación. **Es externa al sistema:** no añade endpoints, no modifica el backend ni el frontend, y no toca el esquema de la base de datos.

## Cómo se ejecuta

Tiene dos puertas a la misma lógica. La interfaz web es la habitual:

```
codigodmindmin.bat
```

Abre el navegador en `http://127.0.0.1:8010`. **Escucha solo en esta máquina:** no es alcanzable desde la red. En el primer arranque pide fijar una contraseña propia del módulo, que queda cifrada en `codigo/admin/.acceso` y no entra en el repositorio. Si se pierde, se borra ese archivo y se vuelve a fijar.

La consola sigue existiendo, como red de seguridad y para cuando no hay navegador a mano:

```
codigodmindmin_consola.bat
```

Las dos se ejecutan con el intérprete del backend, porque el módulo reutiliza sus definiciones de tablas y su función de cifrado, y porque de ahí salen `fastapi`, `uvicorn` y `jinja2`. **No instala ni necesita dependencias propias.**

**Debe correr en la misma máquina que los servicios.** Administrar la configuración y los contenedores desde fuera de la máquina donde están no es posible.

### Qué tiene la interfaz web

Las seis secciones: **Inicio, Cuentas, Entornos, Configuración, Operación y Registro** — las mismas operaciones que la consola, en una barra lateral desde la que se llega a cualquier punto en un clic.

Lo destructivo —reindexar el corpus y restaurar la base— se marca en rojo antes de pulsarlo y **exige escribir `SI`**, igual que en la consola. Lo que un cambio arrastra no se queda en aviso: si hace falta reiniciar los servicios, la propia pantalla ofrece el botón que lo hace.

## Sobre qué actúa

| Almacén | Para qué |
|---|---|
| PostgreSQL | Cuentas y entornos |
| `config/.env` | Modo de operación y parámetros |
| Contenedores, índice y volcados | Operación del sistema |

El sistema lee esos tres. El módulo escribe en ellos. **Ninguno de los tres es el código del sistema**, y por eso no hay nada que revalidar cuando el módulo cambia algo.

Un detalle que hace inmediato el efecto: el sistema **vuelve a leer al usuario y su rol de la base en cada petición**, así que un cambio de rol o de entorno se nota en la siguiente. La excepción es la contraseña: cambiarla no cierra las sesiones abiertas, porque la credencial emitida no depende de ella. Para cerrarlas todas hay que cambiar `JWT_SECRET` y reiniciar.

## Qué hace

**Cuentas** — ver y buscar usuarios · crear docentes y administradores · dar de alta estudiantes de uno en uno o desde un archivo · cambiar el rol o el entorno de una cuenta · restablecer contraseñas.

**Entornos** — ver entornos con su docente y su corpus · crear un entorno **para un docente concreto** · reasignar el docente de un entorno.

**Configuración** — ver la configuración vigente · cambiar el modo de operación · cambiar parámetros · reponer claves de API · restaurar una configuración anterior.

**Operación** — estado de los servicios · arrancar, detener y reiniciar · estado de salud · copia de seguridad de la base · reindexar el corpus de un entorno · restaurar la base desde una copia.

## Lo que corrige respecto al sistema

- **El sistema no valida el rol al registrarse:** quien llama a la API elige el suyo. Aquí el rol lo fija la operación elegida.
- **El sistema no comprueba que el entorno exista** al crear una cuenta. Aquí sí, antes de escribir.
- **`POST /environments` asigna el entorno a quien lo crea** y le reescribe su propio entorno: un administrador que creara un curso se lo quedaba y perdía el suyo. Aquí el entorno se crea **para** un docente, y quien administra no queda tocado.
- **La relación docente–entorno vive en dos sitios** (`environments.teacher_id` y `users.environment_id`). Escribir solo uno deja accesos incoherentes; aquí se actualizan los dos.

## Reglas que cumple siempre

1. **Nada manual.** Los entornos y las cuentas se eligen de una lista: no se teclea ningún identificador. Los valores admitidos los ofrece el módulo.
2. **Los encadenamientos los resuelve el módulo.** Si un cambio necesita reinicio, lo propone y lo hace. Si invalida el índice, lo dice en el momento.
3. **Copia antes de tocar.** Del `.env` en cada modificación; de la base antes de restaurar.
4. **Confirmación explícita** en lo destructivo: reindexar y restaurar.
5. **Los secretos no se muestran completos, no se registran y no salen del módulo.**

## Lo que deja fuera, y por qué

**No da de baja cuentas ni archiva entornos.** `users` no tiene columna de estado y el estado de un entorno solo admite borrador y publicado. Hacerlo exigiría tocar el esquema del sistema.

## Archivos que genera

Todos dentro de esta carpeta, para que borrar el módulo no deje rastro en el sistema:

- `operaciones.jsonl` — registro de lo que se hizo y cuándo. Sin contraseñas.
- `respaldos/` — copias del `.env` y volcados de la base.
- `salidas/` — listados de credenciales generadas. **Llevan contraseñas en claro:** entregarlas y borrar el archivo.
