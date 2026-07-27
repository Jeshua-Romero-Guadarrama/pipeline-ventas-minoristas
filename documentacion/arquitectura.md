# Arquitectura y justificación técnica

El presente documento explica cómo está construido el sistema y, sobre todo, por qué se tomó cada decisión.
Las alternativas descartadas figuran junto con el motivo del descarte, puesto que una decisión sin contexto resulta difícil de revisar cuando las condiciones cambian.

---

## Visión general

El sistema tiene cuatro planos que se pueden operar por separado.

```
┌─────────────────────────────────────────────────────────────────────────┐
│  PLANO DE ORQUESTACIÓN                                                  │
│                                                                         │
│   Airflow (programador + servidor web) sobre PostgreSQL de metadatos    │
│   Define cuándo corre cada cosa y en qué orden                          │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │ dispara
                                 v
┌─────────────────────────────────────────────────────────────────────────┐
│  PLANO DE PROCESAMIENTO                                                 │
│                                                                         │
│   ┌──────────┐   ┌────────────┐   ┌──────────────┐   ┌─────────────┐   │
│   │ ingesta  │──>│ validacion │──>│ transformar  │──>│ persistir   │   │
│   │ pandas   │   │ 6 reglas   │   │ agregaciones │   │ Parquet+CSV │   │
│   └──────────┘   └─────┬──────┘   └──────────────┘   └──────┬──────┘   │
│                        │                                    │           │
│                        v                                    v           │
│                  cuarentena CSV                      almacén + Spark    │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 v
┌─────────────────────────────────────────────────────────────────────────┐
│  PLANO DE ALMACENAMIENTO                                                │
│                                                                         │
│   Sistema de archivos          PostgreSQL                               │
│   ├── detalle_ventas/          ├── crudo      (zona de aterrizaje)      │
│   ├── ingresos_.../            ├── preparado  (vistas de dbt)           │
│   └── analitica_spark/         └── publicado  (tablas finales)          │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                                 v
┌─────────────────────────────────────────────────────────────────────────┐
│  PLANO DE OBSERVABILIDAD                                                │
│                                                                         │
│   pipeline ──push──> Pushgateway ──┐                                    │
│   Airflow  ──statsd─> exportador ──┼──> Prometheus ──> Grafana          │
│   Postgres ─────────> exportador ──┘         │                          │
│                                              └──> reglas de alerta      │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Flujo de datos en detalle

### 1. Ingesta

El módulo `trabajos/ingesta.py` lee el archivo crudo, traduce los encabezados del inglés al vocabulario del proyecto y fuerza los tipos.

La decisión importante es que **no descarta ninguna fila**, ni siquiera las que a simple vista están mal.
Al respecto, un valor que no se puede convertir a número queda como nulo en lugar de cortar la lectura.
La razón es que el motivo de cada descarte tiene que quedar registrado, y eso corresponde a la capa de calidad.
Siempre que la ingesta filtrara por su cuenta, se perdería la trazabilidad y una excepción sin contexto reemplazaría a un reporte que explica qué pasó.

La lectura se hace **por lotes**, no de una sola vez.
Conviene precisar que esa decisión no estaba en el diseño original y se agregó después de que el pipeline muriera por falta de memoria dentro del contenedor de Airflow.
El problema tiene una explicación concreta.
Un millón de filas con ocho columnas de texto recién leídas ocupa varios cientos de megabytes como objetos de Python, y esa es la representación más costosa de todo el recorrido.
En cambio, al convertir cada lote apenas se lee, dicha estructura nunca existe completa, sino solo un lote a la vez.

El resultado es medible, dado que el pipeline completo sobre el archivo entero corre dentro de un contenedor limitado a un gigabyte, cuando antes fallaba con dos.

También se evita `sep=None` en la lectura.
Suena cómodo porque pandas detecta el separador solo, pero obliga a usar su motor escrito en Python, que consume varias veces más memoria y es bastante más lento que el motor en C.
Por ello, el proyecto detecta el separador leyendo los primeros kilobytes del archivo y después usa el motor rápido.

### 2. Validación

El módulo `trabajos/validaciones.py` aplica seis reglas y separa las filas en dos grupos.
Las que pasan siguen adelante, mientras que las que no pasan van a cuarentena con el nombre de la regla que las descartó.

Una fila que incumple varias reglas recibe solo el nombre de la primera del catálogo.
El diseño elegido es un motivo único por fila en lugar de una lista, porque mantiene la suma de los conteos por regla igual al total de rechazos, y eso hace que el tablero de calidad sea interpretable sin explicación adicional.

Por encima de las reglas hay un umbral global.
Siempre que se rechace más del quince por ciento de las filas, el pipeline se detiene sin publicar.
El razonamiento es que perder un uno por ciento constituye ruido normal de un sistema transaccional, mientras que perder la mitad significa que algo cambió en el origen, y publicar ese resultado sería peor que no publicar nada.

### 3. Transformación

El módulo `trabajos/transformaciones.py` calcula el ingreso por línea de factura y arma las agregaciones.

Todas las funciones son puras, en el sentido de que reciben una tabla y devuelven otra, sin tocar disco ni variables globales.
De ese modo se pueden probar con tablas de tres filas armadas a mano, sin levantar ninguna infraestructura, y esa es la razón por la que la batería de pruebas corre en unos pocos segundos.

El redondeo a dos decimales se aplica a nivel de línea y no al final.
El motivo es que el importe de una línea de factura es un valor monetario real, y sumar valores ya redondeados da el mismo resultado que muestra el sistema contable de origen, que es contra lo que se compara.

### 4. Verificación de salida

Antes de escribir nada se comprueba el resultado.
El agregado no puede estar vacío, tampoco puede tener importes negativos ni nulos, y la combinación de fecha y producto tiene que ser única.

Las comprobaciones de salida cierran el círculo.
Dicho de otro modo, las reglas anteriores miran la entrada y estas miran la salida, que es lo que van a consumir los tableros.
En caso de que algo se rompa durante la transformación, se detecta aquí y no en una reunión.

### 5. Persistencia

El módulo `trabajos/persistencia.py` escribe en Parquet y en CSV.

La escritura borra el destino anterior antes de escribir.
Sin ese paso, volver a correr el pipeline sobre una carpeta particionada dejaría conviviendo los archivos de la corrida vieja con los de la nueva y los conteos saldrían duplicados.
Con él, en cambio, la operación es idempotente y se puede reintentar sin consecuencias, que es justamente lo que necesita un orquestador con reintentos automáticos.

### 6. Carga y modelado

El módulo `trabajos/carga_almacen.py` deja las tablas en el esquema `crudo` de PostgreSQL, y dbt construye a partir de ahí las capas `preparado` y `publicado`.

En caso de que el almacén no responda, la función no rompe la corrida, sino que deja constancia en el log y sigue.
Puesto que los resultados en Parquet ya están escritos y siguen siendo válidos, un problema de conectividad no debería invalidar un procesamiento correcto.

---

## Decisiones y trade-offs

### pandas para el pipeline principal

**Alternativas consideradas:** PySpark para todo, Polars y DuckDB.

**Decisión:** El flujo principal usa pandas, y PySpark queda reservado para el análisis que lo justifica.

**Por qué:** El archivo completo son 96 megabytes en CSV y algo más de un millón de filas, de manera que entra en memoria sin esfuerzo.
Levantar una máquina virtual de Java para eso agregaría unos veinte segundos de arranque en cada corrida, más una capa de configuración y depuración, sin ninguna mejora de rendimiento.

**Qué se pierde:** El pipeline no escala más allá de la memoria de una máquina.
Siempre que el volumen creciera un orden de magnitud habría que reescribir la etapa de transformación en Spark.
Ahora bien, el riesgo se mitiga en parte porque las funciones de transformación son puras y la reescritura quedaría contenida en un módulo.

**Por qué no Polars o DuckDB:** Los dos son más rápidos que pandas en este tipo de carga.
Ambos quedaron descartados porque el proyecto es también material de estudio y pandas es lo que más gente sabe leer sin explicación previa.
Es decir, se trata de una decisión de comunicación y no de rendimiento.

### PySpark solo para el análisis distribuido

**Decisión:** El proyecto mantiene un único trabajo de Spark, `trabajos/spark/agregado_ventas.py`, que calcula el ranking mensual con funciones de ventana, la media móvil de siete días y la concentración por país.

**Por qué:** Los tres cálculos citados son el caso donde Spark aporta de verdad.
Una ventana particionada por mes se procesa en paralelo, con cada partición ordenándose en un ejecutor distinto.
En pandas, en cambio, la misma operación sobre todo el histórico obliga a mantener el conjunto entero en memoria mientras ordena.

La decisión de fondo es que el motor se elige por el problema y no al revés.
Usar Spark para leer un CSV de cien megabytes no demuestra dominio de Spark, sino que demuestra que no se evaluó si hacía falta.

### Una sola imagen de Docker para todo el clúster de Spark

**Alternativas consideradas:** Imágenes oficiales de Apache Spark, imágenes de Bitnami e imágenes separadas para maestro y trabajador.

**Decisión:** La imagen se construye desde `python:3.12-slim`, y la usan el maestro, el trabajador y el cliente.

**Por qué:** El controlador de Spark corre dentro del contenedor de Airflow, que usa Python 3.12.
Siempre que los ejecutores usaran otra versión, el trabajo fallaría al deserializar las funciones enviadas, con un error que no dice nada sobre la causa real.
Por ello, fijar la misma versión de Python y la misma de PySpark en ambos lados elimina esa clase de problema por completo.

**Qué se pierde:** La imagen es más grande que una oficial optimizada y hay que mantenerla.
A cambio, no hay sorpresas de compatibilidad.

### Airflow con ejecutor local

**Alternativas consideradas:** CeleryExecutor, KubernetesExecutor, Prefect y Dagster.

**Decisión:** El ejecutor elegido es LocalExecutor.

**Por qué:** El ejecutor local corre las tareas como procesos hijos del programador.
Con este volumen alcanza de sobra, y además evita sumar Redis más trabajadores de Celery, que serían dos servicios más para levantar, monitorear y explicar.

**Qué se pierde:** No hay escalado horizontal de tareas, puesto que todo corre en un contenedor.
Ahora bien, para pasar a Celery habría que cambiar tres variables de entorno y agregar dos servicios al compose, de manera que el costo de migrar más adelante es bajo.

**Por qué Airflow y no Prefect o Dagster:** Airflow tiene la comunidad más grande y es lo que más probablemente encuentre alguien en un equipo real.
Para un proyecto que también sirve como evidencia de habilidades, esa consideración pesa.

### Parquet como formato de salida

**Alternativas consideradas:** CSV solo, Delta Lake y Apache Iceberg.

**Decisión:** La salida se escribe en Parquet particionado por año y mes, con una copia en CSV del agregado principal.

**Por qué Parquet:** Guarda el esquema junto con los datos, comprime por columna y permite leer solo lo necesario.
Sobre este conjunto, el detalle en Parquet comprimido con Zstandard ocupa alrededor de una décima parte de lo que ocupa el CSV equivalente.

**Por qué también CSV:** Es el formato que cualquiera abre en una planilla sin instalar nada, y en la práctica eso resuelve la mitad de los pedidos que llegan a un equipo de datos.

**Por qué no Delta ni Iceberg:** Aportan transacciones y viaje en el tiempo, cosas valiosas cuando hay escrituras concurrentes o hace falta auditar el estado histórico.
Aquí hay un único escritor y una escritura por día, de manera que solo agregarían dependencias.

### PostgreSQL como almacén analítico

**Alternativas consideradas:** DuckDB, ClickHouse, BigQuery o Snowflake.

**Decisión:** El almacén elegido es PostgreSQL, con tres esquemas dentro de la misma base.

**Por qué:** Es transaccional, tiene todas las funciones de ventana que el proyecto necesita, dbt lo soporta de primera y corre en un contenedor de sesenta megabytes.
Con menos de dos millones de filas, un motor columnar no aportaría diferencia perceptible.

**Por qué no DuckDB:** Es excelente para análisis en una sola máquina, pero un archivo local no da acceso concurrente.
Dado que el almacén tiene que poder recibir consultas mientras el pipeline escribe, esa limitación resultó decisiva.

**Por qué no un almacén en la nube:** El proyecto tiene que poder clonarse y correr sin credenciales ni costos.

### Tres esquemas en lugar de tres bases

**Decisión:** Los esquemas `crudo`, `preparado` y `publicado` se crean dentro de la base `analitica`.

**Por qué:** El aislamiento lógico alcanza para separar responsabilidades, y mantener una sola base simplifica las copias de seguridad y las conexiones.
La regla que hace útil la separación es que nadie consulta `crudo` directamente, ya que para eso está `publicado`.

La base de metadatos de Airflow sí está separada.
En caso de que compartiera base con lo analítico, una consulta pesada de un analista podría trabar el programador de tareas.

### Prometheus con Pushgateway

**Alternativas consideradas:** Exponer un endpoint de métricas, escribir a un archivo que Prometheus lea o usar solo logs.

**Decisión:** Las métricas se empujan al Pushgateway al terminar cada corrida.

**Por qué:** El pipeline es un proceso por lotes, de modo que cuando Prometheus fuera a consultarlo el proceso ya terminó.
El Pushgateway existe exactamente para este caso.

**Qué se pierde:** El Pushgateway no distingue entre un trabajo que dejó de correr y uno que corrió y no cambió sus valores.
La limitación se mitiga publicando la marca de tiempo de la última corrida exitosa, sobre la que se define la alerta de datos desactualizados.

### La observabilidad nunca hace fallar el pipeline

**Decisión:** Todo error al publicar métricas se atrapa y solo genera una advertencia en el log.

**Por qué:** Un problema de monitoreo no puede invalidar datos que se calcularon bien.
Es la clase de acoplamiento que convierte una caída menor de infraestructura en una interrupción del servicio de datos.

### Configuración centralizada

**Decisión:** Todo lo configurable vive en `trabajos/configuracion.py` y sale de variables de entorno.

**Por qué:** Cuando el pipeline pasa de la máquina de alguien a un contenedor de Airflow, solo cambian las variables de entorno y el código queda intacto.

La configuración se construye en cada llamada y no como una instancia global de módulo.
De ese modo, las pruebas pueden alterar variables de entorno y obtener una configuración distinta sin reiniciar el intérprete.

### dbt en su propio entorno virtual dentro de la imagen de Airflow

**Decisión:** La instalación de dbt va en `/opt/dbt_entorno`, y se lo invoca por ruta absoluta.

**Por qué:** Airflow y dbt fijan versiones distintas de varias librerías compartidas.
Instalarlos en el mismo entorno termina en un conflicto que no tiene solución limpia.
Por ello se descartó el entorno compartido, ya que aislarlo evita el problema por completo y el costo son unos doscientos megabytes adicionales en la imagen.

### Logs estructurados en JSON

**Decisión:** La salida va en JSON por defecto, con texto plano opcional para desarrollo.

**Por qué:** Dentro de Docker la salida estándar termina en un recolector de logs, y un formato estructurado permite filtrar por etapa, por nivel o por cantidad de filas sin escribir expresiones regulares frágiles.
Cabe señalar que cualquier dato que se pase con el argumento `extra` se incorpora como campo del objeto JSON.

---

## Qué haría falta para llevarlo a producción

El proyecto está pensado para correr en una máquina.
A continuación se listan los cambios que requeriría un entorno real, en orden de prioridad.

| Aspecto | Estado actual | Qué haría falta |
| --- | --- | --- |
| Credenciales | En variables de entorno con valores por defecto | Un gestor de secretos |
| Ejecutor de Airflow | Local, un solo contenedor | Celery o Kubernetes |
| Carga al almacén | Reemplazo completo de tabla | Carga incremental por partición |
| Alta disponibilidad | Una instancia de cada servicio | Réplicas y balanceo |
| Copias de seguridad | No configuradas | Respaldo periódico con prueba de restauración |
| Control de acceso | Un usuario administrador | Roles por función |
| Cifrado | Tráfico en claro dentro de la red interna | TLS entre servicios |
| Linaje de datos | Implícito en el grafo de dbt | Catálogo con linaje a nivel de columna |

Ninguno de estos puntos afecta la corrección de lo que el pipeline calcula.
En rigor, se trata de requisitos de operación y de seguridad que aparecen cuando el sistema deja de correr en una máquina de escritorio.
