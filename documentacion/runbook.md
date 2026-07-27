# Runbook operativo

El presente documento sirve de guía para operar el pipeline y resolver los problemas que aparecen con más frecuencia.
Está escrito pensando en alguien que se encuentra con una alerta a las tres de la mañana y necesita saber qué hacer sin leer todo el código.

---

## Operaciones habituales

### Levantar el sistema completo

```bash
cd pipeline-ventas-minoristas
docker compose --profile completo up -d
docker compose ps
```

La primera vez tarda entre diez y quince minutos, porque construye las imágenes.
Después, se necesitan unos noventa segundos hasta que Airflow queda operativo.

### Verificar que todo está sano

```bash
# Estado de los contenedores
docker compose ps

# Airflow responde
curl -f http://localhost:8080/health

# El almacén acepta conexiones
docker compose exec postgres pg_isready -U analitica -d analitica

# Prometheus ve todos sus objetivos
curl -s http://localhost:9090/api/v1/targets | grep -o '"health":"[^"]*"'

# El clúster de Spark tiene trabajadores registrados
curl -s http://localhost:8081 | grep -o "Alive Workers.*"
```

### Disparar el pipeline a mano

```bash
# A través de Airflow, que es la forma normal
docker compose exec airflow-programador airflow dags trigger ventas_minoristas_diario

# Solo el procesamiento, sin orquestador
docker compose --profile herramientas run --rm pipeline

# Solo el modelado
docker compose --profile herramientas run --rm dbt build
```

### Ver los resultados

```bash
# Reporte de la última corrida
cat salida/reportes/reporte_ultima_corrida.json

# Archivos generados
ls -la salida/

# Consultar el almacén
docker compose exec postgres psql -U analitica -d analitica -c \
  "select fecha, round(ingreso_total, 2) as ingreso, facturas_distintas
   from publicado.pub_resumen_diario order by fecha desc limit 10;"
```

### Detener el sistema

```bash
# Conservando los datos
docker compose --profile completo down

# Borrando todo, incluidos los volúmenes
docker compose --profile completo --profile herramientas down -v
```

---

## Resolución de problemas

### El pipeline falló

**Cómo se manifiesta:** Salta la alerta `PipelineFallo`, o bien el indicador de la última corrida aparece en rojo en Grafana.

**Qué mirar primero:**

```bash
# Registros de la tarea de procesamiento
docker compose exec airflow-programador \
  airflow tasks logs ventas_minoristas_diario procesar_ventas

# O directamente el reporte, si llegó a escribirse
cat salida/reportes/reporte_ultima_corrida.json | head -40
```

**Causas frecuentes y qué hacer:**

| Síntoma en el registro | Causa | Solución |
| --- | --- | --- |
| `No se encontró el archivo de entrada` | Falta el archivo crudo | Correr `python scripts/descargar_dataset.py` o verificar que la muestra esté en `datos/ejemplos/` |
| `El archivo no contiene ninguna fila` | Archivo truncado en el origen | Volver a descargarlo |
| `columnas obligatorias` | Cambió el formato del origen | Revisar `MAPEO_COLUMNAS` en `trabajos/configuracion.py` |
| `Se rechazó el N por ciento` | Degradación de calidad | Ver la sección de rechazos más abajo |
| `El almacén no responde` | PostgreSQL caído o arrancando | Correr `docker compose restart postgres` y esperar |

**Reintentar:** Todas las tareas son idempotentes, de manera que se puede reintentar sin efectos secundarios.

```bash
docker compose exec airflow-programador \
  airflow tasks clear ventas_minoristas_diario --yes
```

---

### Los datos están desactualizados

**Cómo se manifiesta:** Salta la alerta `DatosDesactualizados`, es decir, pasaron más de veintiséis horas sin una corrida exitosa.

**Diagnóstico:**

```bash
# El programador está vivo
docker compose ps airflow-programador

# El grafo no está pausado
docker compose exec airflow-programador airflow dags list | grep ventas

# Últimas corridas y su estado
docker compose exec airflow-programador \
  airflow dags list-runs -d ventas_minoristas_diario --state failed
```

**Causas frecuentes:**

1. **El grafo quedó pausado.** Los grafos nuevos arrancan pausados por configuración, de modo que se despausan con `airflow dags unpause ventas_minoristas_diario`.
2. **El programador está caído.** En ese caso corresponde correr `docker compose restart airflow-programador`.
3. **Las corridas fallan en silencio.** Conviene revisar los registros de la última.

---

### Suben los rechazos de calidad

**Cómo se manifiesta:** Salta la alerta `CalidadDeDatosDegradada`, porque se descarta más del diez por ciento de las filas.

**Diagnóstico:**

```bash
# Qué regla está descartando más
cat salida/reportes/reporte_ultima_corrida.json | python -m json.tool | \
  grep -A 10 conteo_por_regla

# Ver las filas rechazadas
ls -t salida/cuarentena/ | head -1
head -20 salida/cuarentena/$(ls -t salida/cuarentena/ | head -1)
```

**Interpretación según la regla que se disparó:**

| Regla | Qué significa que suba | Acción |
| --- | --- | --- |
| `cantidad_minima` | Llegaron más devoluciones de lo habitual | Suele ser real, conviene verificar con el negocio |
| `precio_en_rango` | Aparecieron importes fuera de rango | Revisar si cambió la moneda o la escala |
| `columnas_obligatorias_sin_nulos` | El origen dejó de completar campos | Escalar al equipo del sistema de origen |
| `fecha_dentro_de_rango` | Fechas mal formateadas | Revisar si cambió el formato de exportación |
| `sin_duplicados_exactos` | El origen envió el archivo dos veces | Verificar el proceso de exportación |

**Nota importante:** El pipeline se detiene solo al llegar al quince por ciento.
Entre el diez y el quince publica igual, pero avisa.
Dicho margen existe para que alguien pueda investigar sin que el servicio de datos se interrumpa.

Siempre que el aumento sea legítimo y permanente, el umbral se ajusta con la variable de entorno `PORCENTAJE_RECHAZO_MAXIMO`.

---

### Permiso denegado al escribir en la carpeta de salida

**Cómo se manifiesta:**

```
No se pudo borrar el resultado anterior en /opt/proyecto/salida/detalle_ventas
por falta de permisos.
```

**Causa:** La carpeta de salida está montada desde la máquina anfitriona y contiene archivos escritos por un usuario distinto al que ejecuta ahora.
La situación aparece siempre que se alterna entre correr el pipeline directamente en la máquina y correrlo dentro de un contenedor, porque cada uno escribe con su propio identificador de usuario.

**Solución:**

```bash
# Vaciar la carpeta de salida desde dentro del contenedor, como root
docker compose exec -u root airflow-programador bash -c \
  "rm -rf /opt/proyecto/salida/* && chown -R 50000:0 /opt/proyecto/salida"
```

**Cómo evitarlo:** Todos los servicios que escriben en la carpeta compartida usan el mismo identificador de usuario, el cincuenta mil, declarado en `docker-compose.yml`.
La situación solo aparece si además se corre el pipeline fuera de Docker sobre la misma carpeta.

---

### Cayó el volumen procesado

**Cómo se manifiesta:** Salta la alerta `CaidaAbruptaDeVolumen`, dado que se procesó menos de la mitad del promedio de la última semana.

**Diagnóstico:**

```bash
# Tamaño del archivo de entrada comparado con lo esperado
ls -lh datos/crudos/

# Filas por etapa en la última corrida
cat salida/reportes/reporte_ultima_corrida.json | python -m json.tool | \
  grep -E "filas_entrada|filas_validas"
```

**Causa más frecuente:** Llegó un archivo parcial porque la exportación del sistema de origen se cortó a mitad de camino.
En consecuencia, los números del tablero van a estar subestimados hasta que se reprocese.

**Solución:** Conseguir el archivo completo y reintentar la corrida.
En caso de que el archivo parcial ya se haya procesado, la reejecución lo sobrescribe todo porque la escritura no es incremental.

---

### El pipeline tarda demasiado

**Cómo se manifiesta:** Salta la alerta `PipelineDemasiadoLento`, porque una etapa superó los quince minutos.

**Diagnóstico:**

```bash
# Qué etapa se está demorando
curl -s 'http://localhost:9090/api/v1/query?query=pipeline_ventas_duracion_segundos'

# Uso de recursos de los contenedores
docker stats --no-stream
```

**Interpretación por etapa:**

| Etapa lenta | Causa probable |
| --- | --- |
| `ingesta` | El archivo creció mucho, o el disco está saturado |
| `validacion` | Poco frecuente, suele ser presión de memoria |
| `transformacion` | Creció la cantidad de productos o de días |
| `persistencia` | Disco lento o sin espacio |
| `carga_almacen` | El almacén está bajo carga o le faltan recursos |

**Solución rápida si es presión de recursos:** Conviene subir la memoria asignada a Docker, o bien bajar `AIRFLOW__CORE__PARALLELISM` para que corran menos tareas a la vez.

---

### Un servicio dejó de responder

**Cómo se manifiesta:** Salta la alerta `ServicioCaido`.

```bash
# Cuál está caído
docker compose ps

# Por qué se cayó
docker compose logs --tail=100 <nombre-del-servicio>

# Reiniciarlo
docker compose restart <nombre-del-servicio>
```

**Si el contenedor reinicia en bucle**, casi siempre se trata de falta de memoria.
En Docker Desktop se sube desde la configuración de recursos, teniendo en cuenta que el sistema completo necesita alrededor de seis gigabytes.

---

### No se puede recargar una tabla del esquema crudo

**Cómo se manifiesta:**

```
No se pudo cargar la tabla crudo.detalle_ventas:
cannot drop table crudo.detalle_ventas because other objects depend on it
```

**Causa:** Los modelos de dbt se construyen sobre las tablas del esquema crudo, y una vista de PostgreSQL queda ligada a la tabla que consulta.
Por ello, si el pipeline intenta borrar la tabla para volver a crearla, el motor se niega.

**Estado actual:** Ya está resuelto en el código.
Al respecto, la carga vacía la tabla en lugar de borrarla, de modo que el objeto sobrevive y las vistas siguen siendo válidas.
Solo se recrea, y en ese caso en cascada, cuando cambió la estructura de columnas.

**Si aparece de todos modos**, significa que alguien creó una dependencia nueva sobre una tabla cruda.
Para ver quién depende de qué se usa la siguiente consulta.

```sql
select dependiente.relname as objeto_dependiente,
       origen.relname      as tabla_origen
from pg_depend d
join pg_rewrite r on r.oid = d.objid
join pg_class dependiente on dependiente.oid = r.ev_class
join pg_class origen on origen.oid = d.refobjid
where origen.relname = 'detalle_ventas'
  and dependiente.relname <> origen.relname;
```

---

### Una tarea de Airflow termina con código de retorno -9

**Cómo se manifiesta:** En el registro de la tarea aparece esta línea y no hay ningún rastro de excepción antes.

```
Task exited with return code -9
```

**Causa:** El nueve negativo es la señal de terminación forzada.
Nadie la envió desde el código, sino que la envió el sistema operativo porque el contenedor superó su límite de memoria.
Puesto que el proceso muere de golpe, no alcanza a escribir un mensaje de error, motivo por el cual el registro queda cortado en seco.

**Diagnóstico:**

```bash
# Cuanta memoria tiene Docker asignada
docker info --format "{{.MemTotal}}"

# Cuanto esta usando cada contenedor
docker stats --no-stream --format "{{.Name}}\t{{.MemUsage}}"
```

**Atención, hay una causa que no tiene nada que ver con la memoria.** Siempre que el proceso muera a los pocos segundos y siempre en el mismo punto, sin importar cuánta memoria se le dé, el problema puede ser un lazo en el sistema de registro.
Airflow ejecuta cada tarea redirigiendo la salida estándar hacia su propio registrador.
En caso de que el código de la tarea reemplace los manejadores del registrador raíz por uno que escribe a la salida estándar, cada mensaje vuelve a entrar al sistema de registro y se reemite indefinidamente, consumiendo memoria a una velocidad enorme.

El proyecto ya lo tiene resuelto en `trabajos/registro.py`, que respeta los manejadores existentes en lugar de reemplazarlos.
La regla general vale para cualquier código que pueda importarse desde otro programa.
Dicho de otro modo, un módulo no debería apropiarse del registrador raíz, porque no es suyo.

Para distinguir un caso del otro conviene comparar cuánto tarda en morir.
Una falta de memoria real crece de forma progresiva y el momento de la muerte varía.
Un lazo de registro, en cambio, mata el proceso siempre en el mismo punto y en pocos segundos.

**Soluciones cuando sí es memoria, en orden de preferencia:**

1. **Subir la memoria de Docker** a seis gigabytes desde la configuración de Docker Desktop, que es la solución correcta siempre que la máquina lo permita.
2. **Levantar solo el perfil de orquestación** en lugar del completo, lo que libera los cuatrocientos megabytes que consumen Grafana y Prometheus.
3. **Procesar la muestra versionada** en vez del histórico completo, cambiando la variable `ARCHIVO_ENTRADA` o moviendo el archivo de `datos/crudos`.
4. **Limitar las filas leídas** con el parámetro `--filas-maximas`, que resulta útil para confirmar que el resto del pipeline funciona antes de resolver la memoria.

---

### Las conexiones del almacén se agotan

**Cómo se manifiesta:** Salta la alerta `AlmacenSinConexionesDisponibles`, o bien aparecen errores de conexión intermitentes.

```bash
# Ver conexiones activas y de dónde vienen
docker compose exec postgres psql -U analitica -d analitica -c \
  "select datname, usename, state, count(*)
   from pg_stat_activity group by 1,2,3 order by 4 desc;"

# Cerrar conexiones inactivas de más de diez minutos
docker compose exec postgres psql -U analitica -d analitica -c \
  "select pg_terminate_backend(pid) from pg_stat_activity
   where state = 'idle' and state_change < now() - interval '10 minutes';"
```

**Causa habitual:** Un proceso que abrió conexiones y no las cerró.
Cabe señalar que el pipeline usa `pool_pre_ping` y reciclado cada media hora justamente para evitarlo.

---

### El programador de Airflow no responde

**Cómo se manifiesta:** Salta la alerta `ProgramadorSinLatido`, de modo que la interfaz web responde pero no se dispara ninguna tarea.

```bash
docker compose logs --tail=200 airflow-programador
docker compose restart airflow-programador

# Si sigue sin arrancar, revisar la base de metadatos
docker compose exec airflow-programador airflow db check
```

**Si la base de metadatos está corrupta**, lo cual es poco frecuente pero posible tras un apagado abrupto, se aplican estos dos comandos.

```bash
docker compose exec airflow-programador airflow db check-migrations
docker compose exec airflow-programador airflow db migrate
```

---

### Fallan tareas en Airflow

**Cómo se manifiesta:** Salta la alerta `TareasDeAirflowFallando`, porque hubo más de tres fallos en una hora.

```bash
# Qué tareas fallaron
docker compose exec airflow-programador \
  airflow tasks states-for-dag-run ventas_minoristas_diario <fecha-de-ejecucion>

# Registro de una tarea concreta
docker compose exec airflow-programador \
  airflow tasks logs ventas_minoristas_diario <nombre-de-tarea>
```

Un patrón de fallos repetidos indica un problema de fondo y no un error puntual.
Siempre que sea la misma tarea, el problema está en esa etapa.
En cambio, si son distintas, suele tratarse de un recurso compartido, casi siempre la memoria o el almacén.

---

### Falla el trabajo de Spark

**Diagnóstico:**

```bash
# El clúster tiene trabajadores
curl -s http://localhost:8081 | grep -i "alive workers"

# Registros del maestro y del trabajador
docker compose logs --tail=100 spark-maestro
docker compose logs --tail=100 spark-trabajador
```

**Causas frecuentes:**

| Error | Causa | Solución |
| --- | --- | --- |
| `Initial job has not accepted any resources` | No hay trabajadores registrados | Reiniciar `spark-trabajador` |
| `Python in worker has different version` | Versiones de Python desalineadas | Reconstruir las dos imágenes |
| `Connection refused to driver` | El ejecutor no alcanza al controlador | Verificar `SPARK_DRIVER_HOST` |
| `Path does not exist` | Falta el Parquet de entrada | Correr primero el pipeline de Python |

**Salida de emergencia:** El trabajo funciona igual en modo local, sin clúster.

```bash
docker compose --profile herramientas run --rm \
  -e SPARK_MASTER_URL="local[*]" pipeline \
  python trabajos/spark/agregado_ventas.py
```

---

### Fallan las pruebas de dbt

```bash
# Ver qué prueba falló y por qué
docker compose --profile herramientas run --rm dbt test

# Las filas que fallaron quedan guardadas en el almacén
docker compose exec postgres psql -U analitica -d analitica -c \
  "\dt preparado.*"
```

Puesto que `store_failures` está activado, cada prueba que falla deja una tabla con las filas problemáticas, de manera que no hay que reconstruir la consulta a mano.

| Prueba que falla | Qué significa |
| --- | --- |
| `los_totales_coinciden_entre_capas` | Hubo filas duplicadas o perdidas al agregar |
| `el_resumen_diario_coincide_con_el_detalle` | Un día quedó mal calculado |
| `no_hay_importes_ni_cantidades_negativas` | Error de cálculo en la transformación |
| `la_participacion_del_ranking_es_coherente` | Problema en las funciones de ventana |
| `no_hay_huecos_largos_en_la_serie` | Solo advierte, hay un período sin ventas |
| `unique` sobre `fecha` y `producto_id` | La agregación dejó de colapsar bien |

---

### Falla la construcción de las imágenes por certificados

**Cómo se manifiesta:**

```
SSLError(SSLCertVerificationError(1, '[SSL: CERTIFICATE_VERIFY_FAILED]
certificate verify failed: unable to get local issuer certificate'))
```

**Causa:** La red intercepta el tráfico cifrado y lo vuelve a firmar con un certificado propio de la organización.
El anfitrión confía en él, pero el contenedor no.

**Solución:** Copiar el certificado raíz de la entidad que intercepta a `docker/certificados/` con extensión `.crt`.
Los Dockerfiles lo detectan solos, y el procedimiento completo está en `docker/certificados/LEEME.md`.

Para averiguar quién intercepta se usa el siguiente comando.

```bash
docker run --rm python:3.12-slim-bookworm sh -c \
  "apt-get update -qq && apt-get install -y -qq openssl && \
   echo | openssl s_client -connect pypi.org:443 2>/dev/null | grep 'i:'"
```

---

## Mantenimiento periódico

| Frecuencia | Tarea | Comando |
| --- | --- | --- |
| Diaria | Revisar que la corrida terminó bien | Tablero de Grafana |
| Semanal | Revisar la cuarentena acumulada | `ls -la salida/cuarentena/` |
| Semanal | Limpiar cuarentenas viejas | `find salida/cuarentena -mtime +30 -delete` |
| Mensual | Revisar el crecimiento del almacén | Consulta a `publicado.vista_tamanio_tablas` |
| Mensual | Actualizar dependencias | Revisar `requisitos.txt` y correr las pruebas |
| Trimestral | Revisar umbrales de calidad | Comparar contra el histórico de rechazos |

### Limpiar registros viejos de Airflow

```bash
docker compose exec airflow-programador \
  airflow db clean --clean-before-timestamp "$(date -d '90 days ago' +%Y-%m-%d)" --yes
```

### Recuperar espacio en disco

```bash
# Imágenes y capas sin usar
docker system prune -a

# Resultados de corridas anteriores
rm -rf salida/reportes/reporte_2*.json
```

---

## Contactos y escalamiento

| Nivel | Cuándo | Qué hacer |
| --- | --- | --- |
| 1 | Alerta de severidad media | Seguir este runbook |
| 2 | Alerta crítica o el runbook no resolvió | Revisar registros y arquitectura |
| 3 | Pérdida o corrupción de datos | Detener el pipeline, no reintentar, preservar la cuarentena |

**Regla importante ante corrupción de datos:** No conviene reintentar.
La escritura es de reemplazo completo, de manera que una reejecución sobre datos malos sobrescribe la evidencia.
Por ello, primero hay que copiar `salida/` y `datos/crudos/` a un lugar seguro.
