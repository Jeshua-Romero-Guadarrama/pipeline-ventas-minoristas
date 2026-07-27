# Guía de demostración

El presente documento reúne las instrucciones para reproducir el funcionamiento completo del sistema.
Están pensadas para seguirse de arriba abajo sin conocimiento previo del proyecto.

Hay dos recorridos disponibles.
El corto muestra el resultado en cinco minutos sin Docker, mientras que el completo levanta toda la infraestructura y recorre cada plano del sistema.

---

## Recorrido corto, cinco minutos

El recorrido corto solo necesita Python 3.11 o superior.

### Paso 1. Clonar e instalar

```bash
git clone https://github.com/Jeshua-Romero-Guadarrama/pipeline-ventas-minoristas.git
cd pipeline-ventas-minoristas

python -m venv .venv
source .venv/bin/activate          # en Windows: .venv\Scripts\activate
pip install -r requisitos.txt
```

### Paso 2. Correr las pruebas

Antes de ejecutar nada conviene comprobar que la lógica es correcta.

```bash
python -m pytest pruebas -v
```

**Qué se espera ver:** Setenta pruebas en verde en menos de quince segundos.

```
pruebas/test_extremo_a_extremo.py ...........                    [ 15%]
pruebas/test_ingesta.py ............                             [ 32%]
pruebas/test_metricas.py .........                               [ 45%]
pruebas/test_persistencia.py .........                           [ 58%]
pruebas/test_transformaciones.py .................               [ 82%]
pruebas/test_validaciones.py ............                        [100%]

======================= 70 passed in 12.01s ========================
```

### Paso 3. Ejecutar el pipeline

La corrida se hace sobre la muestra versionada, que ya viene en el repositorio.

```bash
python ejecutar_pipeline.py --sin-almacen --sin-metricas --formato-log texto
```

**Qué se espera ver:** El recorrido de las etapas y, al final, el resumen.

```
====================================================================
  RESUMEN DE LA CORRIDA DEL PIPELINE DE VENTAS
====================================================================
  Corrida            20260726-141252
  Archivo de entrada datos/ejemplos/ventas_minoristas_muestra.csv
--------------------------------------------------------------------
  Filas leídas       52,778
  Filas válidas      50,006
  Filas rechazadas   2,772 (5.2522 por ciento)
--------------------------------------------------------------------
  Ingreso total      1,024,791.23
  ...
```

### Paso 4. Mirar los resultados

```bash
ls -la salida/

# El agregado principal, que es lo que pide el enunciado
head -5 salida/ingresos_por_producto_fecha.csv

# Las filas descartadas, con el motivo de cada una
head -5 salida/cuarentena/rechazados_*.csv

# El reporte completo de la corrida
cat salida/reportes/reporte_ultima_corrida.json
```

### Paso 5. Correr con el archivo completo

```bash
python scripts/descargar_dataset.py
python ejecutar_pipeline.py --sin-almacen --sin-metricas --formato-log texto
```

La descarga son unos cuarenta y cinco megabytes, y la conversión desde Excel tarda unos minutos.
Después, el pipeline procesa 1,067,371 filas en menos de treinta segundos.

**Resultado esperado con el archivo completo:**

```
  Filas leídas       1,067,371
  Filas válidas      1,007,894
  Filas rechazadas   59,477 (5.5723 por ciento)
  Ingreso total      20,476,082.15
  Unidades vendidas  11,204,828
  Productos          4,744
  Días cubiertos     604
  Período            2009-12-01 a 2011-12-09
```

---

## Recorrido completo con Docker

El recorrido completo necesita Docker con Compose v2 y alrededor de seis gigabytes de memoria disponibles.

### Paso 1. Construir las imágenes

```bash
cd pipeline-ventas-minoristas
cp .env.ejemplo .env
docker compose build
```

**Cuánto tarda:** Entre diez y quince minutos la primera vez, porque descarga las imágenes base, instala Java y resuelve las dependencias de Python.

> **En caso de que la construcción falle con un error de certificado SSL,** la red está interceptando el tráfico cifrado.
> La solución está en `docker/certificados/LEEME.md` y consiste en copiar un archivo.

### Paso 2. Levantar todos los servicios

```bash
docker compose --profile completo up -d
docker compose ps
```

**Qué se espera ver:** Once contenedores, con los que tienen comprobación de salud en estado saludable.

```
NAME                             STATUS
pipeline-postgres                Up (healthy)
pipeline-airflow-servidor        Up (healthy)
pipeline-airflow-programador     Up (healthy)
pipeline-spark-maestro           Up (healthy)
pipeline-spark-trabajador        Up
pipeline-prometheus              Up
pipeline-grafana                 Up
pipeline-pushgateway             Up
pipeline-statsd-exportador       Up
pipeline-postgres-exportador     Up
```

Airflow tarda entre sesenta y noventa segundos en quedar operativo tras el arranque del contenedor.

### Paso 3. Recorrer las interfaces

| Servicio | Dirección | Credenciales |
| --- | --- | --- |
| Airflow | http://localhost:8080 | admin / admin |
| Grafana | http://localhost:3000 | admin / admin |
| Prometheus | http://localhost:9090 | sin credenciales |
| Spark | http://localhost:8081 | sin credenciales |
| Pushgateway | http://localhost:9091 | sin credenciales |

**Qué mostrar en cada una:**

- **Airflow.** Conviene abrir la lista con los dos grafos, entrar en `ventas_minoristas_diario` y ver la vista de grafo, donde se distinguen los grupos de tareas y el paralelismo entre dbt y Spark.
- **Spark.** Conviene mostrar el nodo maestro con un trabajador registrado, sus núcleos y su memoria disponible.
- **Prometheus.** En su interfaz se recorre el menú de objetivos, con las cuatro fuentes en verde, y el menú de reglas, con las nueve alertas cargadas.
- **Grafana.** Aparece la carpeta "Pipeline de ventas" con el tablero aprovisionado automáticamente, que al principio estará vacío porque todavía no corrió nada.

### Paso 4. Disparar el pipeline desde Airflow

Desde la interfaz se activa el interruptor de `ventas_minoristas_diario` y se pulsa el botón de ejecución.
También se puede hacer desde la línea de comandos.

```bash
docker compose exec airflow-programador \
  airflow dags unpause ventas_minoristas_diario

docker compose exec airflow-programador \
  airflow dags trigger ventas_minoristas_diario
```

**Qué se espera ver:** Las tareas cambiando de color en la vista de grafo a medida que avanzan.

1. `preparacion` verifica el archivo y el almacén, y tarda segundos.
2. `procesar_ventas` corre el pipeline completo, entre treinta segundos y dos minutos según el archivo.
3. `modelado_dbt` y `analisis_distribuido` corren en paralelo.
4. `resumen_de_la_corrida` imprime los números finales en su registro.

**Dónde mirar el resultado:** En la tarea `resumen_de_la_corrida`, dentro de la pestaña de registros.

### Paso 5. Ver los datos en el almacén

```bash
docker compose exec postgres psql -U analitica -d analitica
```

```sql
-- Qué se construyó
\dn
\dt crudo.*
\dt publicado.*

-- El modelo principal
select fecha, producto_id, ingreso_total, unidades_vendidas
from publicado.pub_ingresos_producto_fecha
order by ingreso_total desc
limit 10;

-- La serie diaria con su media móvil
select fecha, ingreso_total, ingreso_media_movil_7d, facturas_distintas
from publicado.pub_resumen_diario
order by fecha desc
limit 15;

-- Los productos que más facturaron
select posicion, producto_id, descripcion_producto,
       ingreso_total, participacion_acumulada
from publicado.pub_ranking_productos
order by posicion
limit 10;

-- Cuántos productos explican el ochenta por ciento del ingreso
select count(*)
from publicado.pub_ranking_productos
where participacion_acumulada <= 80;

-- Distribución geográfica
select pais, ingreso_total, participacion_porcentual, tipo_de_mercado
from publicado.pub_ventas_por_pais
order by posicion
limit 10;
```

### Paso 6. Ver el tablero de Grafana con datos

Conviene volver a http://localhost:3000 y abrir el tablero, que ahora ya tiene información.

**Qué señalar:**

- El indicador de resultado, que aparece en verde.
- El gráfico de filas por etapa, donde se ve la caída entre ingesta y validación, que es exactamente lo que descartaron las reglas de calidad.
- El porcentaje de rechazo, que queda por debajo de la línea de umbral.
- El desglose de rechazos por regla, donde se ve que la mayoría son duplicados y devoluciones.
- Las métricas de Airflow, con las tareas exitosas del grafo que acaba de correr.

### Paso 7. Ver las métricas crudas

```bash
# Lo que empujó el pipeline
curl -s http://localhost:9091/metrics | grep pipeline_ventas

# Consultar Prometheus directamente
curl -s 'http://localhost:9090/api/v1/query?query=pipeline_ventas_ingreso_total' \
  | python -m json.tool
```

### Paso 8. Ver el resultado del trabajo distribuido

```bash
ls -R salida/analitica_spark/
```

A continuación se puede leer con Python.

```python
import pandas as pd

ranking = pd.read_parquet("salida/analitica_spark/ranking_mensual_productos")
print(ranking.head(20))

tendencia = pd.read_parquet("salida/analitica_spark/tendencia_diaria")
print(tendencia.tail(20))

paises = pd.read_parquet("salida/analitica_spark/concentracion_por_pais")
print(paises.head(10))
```

### Paso 9. Demostrar que la calidad de datos funciona

La prueba con datos deliberadamente malos es la más interesante de mostrar, porque demuestra que el sistema detecta problemas en vez de propagarlos.

```bash
# Crear un archivo con datos deliberadamente malos
cat > datos/crudos/archivo_roto.csv <<'CSV'
Invoice,StockCode,Description,Quantity,InvoiceDate,Price,Customer ID,Country
489434,22086,PRODUCTO NORMAL,10,2009-12-01 07:45:00,2.50,13085,UNITED KINGDOM
C489435,22086,DEVOLUCION,-10,2009-12-01 08:00:00,2.50,13085,UNITED KINGDOM
489436,AJUSTE,CARGO ADMINISTRATIVO,1,2009-12-01 08:15:00,99999.00,13085,UNITED KINGDOM
489437,,SIN CODIGO,5,2009-12-01 08:30:00,3.00,13085,UNITED KINGDOM
489438,22086,FECHA IMPOSIBLE,3,2099-01-01 09:00:00,2.50,13085,UNITED KINGDOM
CSV

python ejecutar_pipeline.py \
  --entrada datos/crudos/archivo_roto.csv \
  --sin-almacen --sin-metricas --formato-log texto
```

**Qué se espera ver:** El pipeline se detiene con un mensaje explícito, porque el ochenta por ciento de las filas se rechazó y eso supera el umbral tolerado.

```
El pipeline no pudo completarse. Se rechazó el 80.0 por ciento de las filas,
por encima del máximo tolerado de 15.0. Detalle por regla:
{'columnas_obligatorias_sin_nulos': 1, 'fecha_dentro_de_rango': 1,
 'cantidad_minima': 1, 'precio_en_rango': 1, ...}
```

Adicionalmente, el código de salida es 1, que es lo que Airflow interpreta como fallo.

```bash
echo $?    # devuelve 1
```

### Paso 10. Demostrar la idempotencia

```bash
python ejecutar_pipeline.py --sin-almacen --sin-metricas > /dev/null
md5sum salida/ingresos_por_producto_fecha.csv

python ejecutar_pipeline.py --sin-almacen --sin-metricas > /dev/null
md5sum salida/ingresos_por_producto_fecha.csv
```

**Qué se espera ver:** El mismo resumen en las dos corridas.
Dicho de otro modo, reprocesar no duplica ni acumula, que es lo que permite reintentar una tarea fallida sin consecuencias.

### Paso 11. Apagar

```bash
# Conservando los datos
docker compose --profile completo down

# Borrando todo
docker compose --profile completo --profile herramientas down -v
```

---

## Guion sugerido para una presentación de quince minutos

| Minuto | Qué mostrar | Qué decir |
| --- | --- | --- |
| 0 a 2 | El problema y el conjunto de datos | Un millón de líneas de factura reales con problemas reales |
| 2 a 4 | Las pruebas corriendo | La lógica está verificada antes de tocar ningún dato |
| 4 a 6 | El pipeline en la terminal | Las etapas, el resumen y los números finales |
| 6 a 8 | Los archivos generados | Parquet particionado, CSV, cuarentena y reporte |
| 8 a 10 | Airflow | El grafo, el paralelismo entre dbt y Spark |
| 10 a 12 | El almacén | Las tres capas y una consulta de negocio |
| 12 a 14 | Grafana | El estado, la calidad y las alertas definidas |
| 14 a 15 | El archivo roto | El sistema se detiene en vez de publicar algo mal |

El paso del archivo roto conviene dejarlo para el final, puesto que es lo que mejor demuestra que el pipeline no solo procesa, sino que también protege.

---

## Problemas frecuentes durante la demostración

| Problema | Solución rápida |
| --- | --- |
| Airflow todavía no responde | Esperar noventa segundos desde el arranque |
| El grafo no aparece en la lista | Correr `docker compose restart airflow-programador` |
| Grafana muestra paneles vacíos | Correr el pipeline al menos una vez |
| Falla la construcción por certificados | Ver `docker/certificados/LEEME.md` |
| El puerto 8080 está ocupado | Cambiar el mapeo en `docker-compose.yml` |
| El trabajo de Spark no arranca | Verificar que hay un trabajador en http://localhost:8081 |

Ante cualquier otra cosa, `documentacion/runbook.md` tiene el diagnóstico detallado.
