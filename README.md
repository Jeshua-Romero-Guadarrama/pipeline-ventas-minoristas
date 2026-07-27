# Pipeline de datos de ventas minoristas

El presente proyecto implementa un pipeline de datos extremo a extremo sobre un histórico real de transacciones de comercio minorista.
El sistema toma un archivo crudo de poco más de un millón de líneas de factura, lo valida, lo transforma y publica los agregados que responden la pregunta de negocio, todo ello de forma reproducible y monitoreada.

Conviene precisar que el proyecto no busca acumular herramientas sino mostrar un flujo completo que funcione.
De ese modo, cada pieza está donde está porque resuelve un problema concreto que se explica en su sección.

---

## Qué hace

El objetivo del pipeline consiste en calcular el ingreso generado por cada producto en cada fecha, partiendo de líneas de factura sueltas.

```
ingreso_total = cantidad x precio_unitario
```

Dicho cálculo se agrupa por fecha y por producto, de manera que el resultado es la tabla que consumen los tableros y los análisis posteriores.

```
fecha        producto_id   ingreso_total   unidades_vendidas   facturas_distintas
2009-12-01   84879              1919.28                1272                   12
2009-12-01   22086              1327.37                 424                   31
2009-12-01   35400               783.50                  50                   17
```

A continuación se representa el recorrido completo.

```
archivo crudo
     |
     v
  ingesta          lee el CSV, traduce columnas y fuerza tipos
     |
     v
 validacion        aplica seis reglas de calidad y aparta lo que no pasa
     |
     +---> cuarentena (CSV con el motivo de cada rechazo)
     |
     v
transformacion     calcula el ingreso y arma las agregaciones
     |
     v
 verificacion      comprueba invariantes sobre el resultado
     |
     v
persistencia       escribe Parquet particionado y CSV
     |
     +---> PostgreSQL ---> dbt ---> capas preparado y publicado
     |
     +---> PySpark ---> analisis distribuido
     |
     v
  metricas         publica en Prometheus, se ven en Grafana
```

---

## El conjunto de datos

El conjunto elegido es **Online Retail II**, un histórico real publicado por el repositorio de aprendizaje automático de la Universidad de California en Irvine y también disponible en Kaggle.
Dicho conjunto registra todas las transacciones de un comercio minorista británico dedicado a artículos de regalo entre el 1 de diciembre de 2009 y el 9 de diciembre de 2011.

Cabe señalar que no se trata de un conjunto sintético.
Al respecto, trae exactamente los problemas que aparecen en un sistema transaccional de verdad, motivo por el cual resulta útil.

| Característica | Valor |
| --- | --- |
| Filas totales | 1,067,371 |
| Período | 2009-12-01 al 2011-12-09 |
| Productos distintos | 5,305 |
| Países | 43 |
| Formato original | Excel con dos hojas, una por año comercial |

### Estructura

| Columna original | Nombre en el proyecto | Tipo | Descripción |
| --- | --- | --- | --- |
| `Invoice` | `factura` | texto | Número de comprobante (los que empiezan con C corresponden a devoluciones). |
| `StockCode` | `producto_id` | texto | Código de artículo del comercio. |
| `Description` | `descripcion` | texto | Nombre del artículo (admite nulos). |
| `Quantity` | `cantidad` | entero | Unidades vendidas (la cantidad es negativa en las devoluciones). |
| `InvoiceDate` | `fecha_hora` | marca de tiempo | Momento exacto de la operación. |
| `Price` | `precio_unitario` | decimal | Precio unitario en libras esterlinas. |
| `Customer ID` | `cliente_id` | entero | Identificador de cliente (admite nulos). |
| `Country` | `pais` | texto | País de la operación. |

### Problemas reales que trae y cómo se tratan

| Problema | Cuántas filas | Tratamiento |
| --- | --- | --- |
| Devoluciones con cantidad negativa | 22,950 | Quedan apartadas porque el objetivo es medir ingresos por venta. |
| Cargos administrativos con importes desmedidos | 2,768 | Quedan apartadas con el límite superior de precio. |
| Líneas de factura repetidas exactas | 33,759 | Solo se conserva la primera aparición. |
| Descripciones ausentes | unas 4,300 | Quedan conservadas (la descripción no es una columna clave). |
| Cliente sin identificar | unas 243,000 | Quedan conservadas (muchas ventas de mostrador no se asocian a ningún cliente). |

Con el archivo completo, el pipeline descarta el **5.57 por ciento** de las filas, cifra muy por debajo del quince por ciento a partir del cual se detiene.

### Qué archivo se usa

El repositorio incluye una **muestra de 52,778 filas** en `datos/ejemplos/ventas_minoristas_muestra.csv`, formada por 2,600 facturas completas.
Conviene precisar que no se trata de un recorte de filas sueltas, puesto que se eligen comprobantes enteros para que los conteos de facturas distintas sigan teniendo sentido.

En caso de que el histórico completo esté presente, el pipeline lo usa, y si no lo está, cae en la muestra.
De ese modo, quien clona el repositorio puede correr todo sin descargar nada.

Para trabajar con el archivo completo se ejecuta el siguiente comando.

```bash
python scripts/descargar_dataset.py
```

---

## Puesta en marcha

### Opción 1. Solo el pipeline, sin Docker

La vía más rápida para ver el resultado únicamente necesita Python 3.11 o superior.

```bash
git clone https://github.com/Jeshua-Romero-Guadarrama/pipeline-ventas-minoristas.git
cd pipeline-ventas-minoristas

python -m venv .venv
source .venv/bin/activate          # en Windows: .venv\Scripts\activate
pip install -r requisitos.txt

python ejecutar_pipeline.py --sin-almacen --sin-metricas --formato-log texto
```

Los resultados quedan en `salida/`.

### Opción 2. La pila completa con Docker

La segunda opción levanta el orquestador, el almacén, el clúster de procesamiento y el monitoreo, de modo que necesita Docker con Compose v2.

```bash
git clone https://github.com/Jeshua-Romero-Guadarrama/pipeline-ventas-minoristas.git
cd pipeline-ventas-minoristas

cp .env.ejemplo .env

docker compose build
docker compose --profile completo up -d
```

La primera construcción tarda entre diez y quince minutos, porque descarga las imágenes base e instala Java y las dependencias de Python.
En cambio, las siguientes aprovechan la caché y tardan segundos.

Una vez que la pila está arriba, los servicios quedan disponibles en las direcciones que siguen.

| Servicio | Dirección | Credenciales |
| --- | --- | --- |
| Airflow | http://localhost:8080 | admin / admin |
| Grafana | http://localhost:3000 | admin / admin |
| Prometheus | http://localhost:9090 | sin credenciales |
| Spark | http://localhost:8081 | sin credenciales |
| Pushgateway | http://localhost:9091 | sin credenciales |
| PostgreSQL | localhost:5432 | analitica / analitica |

Para disparar el flujo completo se usan estos dos comandos.

```bash
docker compose exec airflow-programador airflow dags unpause ventas_minoristas_diario
docker compose exec airflow-programador airflow dags trigger ventas_minoristas_diario
```

También se puede ejecutar cada etapa por separado.

```bash
docker compose --profile herramientas run --rm pipeline
docker compose --profile herramientas run --rm dbt deps
docker compose --profile herramientas run --rm dbt build
```

### Opción 3. Con Make

```bash
make ayuda            # lista todo lo disponible
make instalar         # entorno virtual y dependencias
make pipeline         # corrida local
make levantar         # pila completa en Docker
make verificar        # estilo y pruebas, igual que en integración continua
make todo             # levanta la pila y ejecuta el flujo entero
```

---

## Estructura del proyecto

Las carpetas están en español para mantener la coherencia con el resto del código, de manera que la correspondencia con la nomenclatura habitual resulta directa.

```
.
├── datos/                          # (data) archivos de entrada
│   ├── crudos/                     #   histórico completo, no versionado
│   └── ejemplos/                   #   muestra versionada
├── salida/                         # (output) resultados generados
├── trabajos/                       # (jobs) lógica del pipeline
│   ├── configuracion.py            #   rutas, umbrales y conexiones
│   ├── registro.py                 #   logs estructurados en JSON
│   ├── metricas.py                 #   publicación hacia Prometheus
│   ├── ingesta.py                  #   lectura y normalización
│   ├── validaciones.py             #   reglas de calidad
│   ├── transformaciones.py         #   cálculos de negocio
│   ├── persistencia.py             #   escritura en Parquet y CSV
│   ├── carga_almacen.py            #   carga en PostgreSQL
│   └── spark/                      #   trabajos distribuidos
├── pruebas/                        # (tests) batería de pruebas
├── orquestacion/dags/              # grafos de Airflow
├── dbt/                            # proyecto de modelado
│   ├── modelos/preparacion/        #   capa de limpieza
│   ├── modelos/intermedio/         #   capa de enriquecimiento
│   ├── modelos/publicacion/        #   capa final
│   └── pruebas/                    #   pruebas de datos propias
├── observabilidad/                 # Prometheus, Grafana y StatsD
├── docker/                         # Dockerfiles y scripts de arranque
├── documentacion/                  # arquitectura, runbook y guía de demo
├── scripts/                        # utilidades de datos
├── .github/workflows/              # integración continua
├── docker-compose.yml
├── ejecutar_pipeline.py            # (run_pipeline) punto de entrada
├── Makefile
└── README.md
```

---

## Ejecución del pipeline

```bash
python ejecutar_pipeline.py [opciones]
```

| Opción | Qué hace |
| --- | --- |
| `--entrada RUTA` | Indica el archivo a procesar (por defecto se resuelve solo). |
| `--filas-maximas N` | Limita las filas leídas, lo que resulta útil para una prueba rápida. |
| `--sin-almacen` | Salta la carga en PostgreSQL. |
| `--sin-metricas` | No publica métricas en Prometheus. |
| `--formato-log json\|texto` | Fija el formato de los registros. |
| `--nivel-log NIVEL` | Admite DEBUG, INFO, WARNING o ERROR. |

A continuación se muestran algunos ejemplos de uso.

```bash
# Corrida rápida con las primeras diez mil filas
python ejecutar_pipeline.py --filas-maximas 10000 --sin-almacen --formato-log texto

# Corrida completa contra el almacén
python ejecutar_pipeline.py

# Solo la muestra versionada
python ejecutar_pipeline.py --entrada datos/ejemplos/ventas_minoristas_muestra.csv
```

### Qué produce

```
salida/
├── detalle_ventas/                         # Parquet particionado por año y mes
│   └── anio=2009/mes=12/...
├── ingresos_por_producto_fecha/            # Parquet, resultado principal
├── ingresos_por_producto_fecha.csv         # el mismo, para abrir en planilla
├── resumen_diario/                         # Parquet, serie temporal
├── ranking_productos.csv                   # los 25 productos que más facturaron
├── analitica_spark/                        # salidas del trabajo distribuido
├── cuarentena/
│   └── rechazados_AAAAMMDD-HHMMSS.csv      # filas descartadas con su motivo
└── reportes/
    ├── reporte_AAAAMMDD-HHMMSS.json        # reporte de cada corrida
    └── reporte_ultima_corrida.json         # la más reciente
```

Adicionalmente, en el almacén analítico quedan las siguientes tablas.

| Esquema | Tabla | Contenido |
| --- | --- | --- |
| `crudo` | `detalle_ventas` | Una fila por línea de factura validada. |
| `crudo` | `ingresos_por_producto_fecha` | Agregado calculado por Python. |
| `crudo` | `resumen_diario` | Métricas diarias calculadas por Python. |
| `preparado` | `prep_ventas` | Vista normalizada, entrada de todo lo demás. |
| `preparado` | `int_ventas_enriquecidas` | Vista con calendario y segmentos. |
| `publicado` | `pub_ingresos_producto_fecha` | Modelo principal. |
| `publicado` | `pub_resumen_diario` | Serie diaria con media móvil. |
| `publicado` | `pub_ranking_productos` | Ranking con participación acumulada. |
| `publicado` | `pub_ventas_por_pais` | Distribución geográfica. |

### Resultado con el archivo completo

```
Filas leídas       1.067.371
Filas válidas      1.007.894
Filas rechazadas      59.477   (5,57 por ciento)

Ingreso total     20.476.082,15
Unidades vendidas    11.204.828
Productos                 4.744
Días cubiertos              604
Período           2009-12-01 a 2011-12-09
```

---

## Calidad de datos

Antes de transformar se aplican seis reglas.
Al respecto, cada fila que incumple alguna se guarda en cuarentena junto con el nombre de la regla que la descartó, de manera que ninguna se pierde en silencio.

| Regla | Qué comprueba |
| --- | --- |
| `columnas_obligatorias_sin_nulos` | Producto, cantidad, fecha y precio están presentes. |
| `producto_identificable` | El código de producto no está vacío. |
| `fecha_dentro_de_rango` | La fecha se interpreta y no es futura. |
| `cantidad_minima` | La cantidad llega al mínimo configurado. |
| `precio_en_rango` | El precio queda entre el mínimo y el máximo. |
| `sin_duplicados_exactos` | No se repite la misma línea de factura. |

Una fila que incumple varias reglas recibe el nombre de la primera del catálogo.
De ese modo, la suma de los conteos por regla coincide siempre con el total de rechazos, que es lo que hace confiable el tablero de calidad.

Después de transformar se verifica el resultado.
El agregado no puede estar vacío, tampoco puede tener importes negativos ni nulos, y la combinación de fecha y producto tiene que ser única.
En caso de que algo de eso falle, no se publica nada.

Por encima de las reglas se sitúa el umbral global.
Siempre que se rechace más del quince por ciento de las filas, el pipeline se detiene.
El razonamiento es que perder un uno por ciento constituye ruido normal de un sistema transaccional, mientras que perder la mitad significa que algo cambió en el origen (publicar ese resultado sería peor que no publicar nada).

---

## Pruebas

```bash
make pruebas          # o: python -m pytest pruebas -v
make cobertura        # con informe de cobertura
```

La batería reúne setenta pruebas repartidas en seis archivos, más un séptimo que solo corre dentro del contenedor de Airflow.

| Archivo | Qué cubre |
| --- | --- |
| `test_ingesta.py` | Traducción de encabezados, tipos, errores de lectura. |
| `test_validaciones.py` | Cada regla por separado y el corte por umbral. |
| `test_transformaciones.py` | Los cálculos de negocio con valores verificables a mano. |
| `test_persistencia.py` | Escritura, relectura e idempotencia. |
| `test_metricas.py` | Que un fallo de monitoreo no interrumpa la corrida. |
| `test_extremo_a_extremo.py` | El pipeline completo y sus códigos de salida. |
| `test_dags.py` | Que los grafos de Airflow carguen sin errores de importación. |

El último se omite cuando Airflow no está instalado, situación habitual al correr las pruebas fuera del contenedor.
Por ello, se prefiere esa omisión antes que convertir a Airflow en una dependencia obligatoria del desarrollo local.

Ninguna prueba necesita servicios levantados ni el archivo real.
Cada caso arma sus propios datos, con la cantidad justa de filas para ejercitar una regla y con valores elegidos para poder verificar la cuenta sin calculadora.

A ello se suman las pruebas de datos de dbt, que corren sobre el almacén ya construido.
Entre ellas hay pruebas genéricas de unicidad, ausencia de nulos y valores aceptados, más cinco pruebas propias que comparan totales entre capas.

---

## Decisiones técnicas

### pandas para el pipeline principal y PySpark para el análisis

El archivo completo entra en memoria sin problemas.
Puesto que es así, se descartó usar PySpark para todo el flujo, ya que levantar una máquina virtual de Java para procesar un gigabyte agregaría veinte segundos de arranque y una capa de complejidad sin ninguna ganancia.

PySpark se reserva entonces para lo que sí justifica un motor distribuido, que son las funciones de ventana sobre todo el histórico.
El ranking mensual y la media móvil de siete días constituyen el caso donde cada partición se procesa en paralelo y el diseño rinde.

La decisión de fondo es que el motor se elige por el problema y no al revés.

### Parquet como formato de salida

Parquet guarda el esquema junto con los datos, de modo que no hay que adivinar tipos al releer.
Adicionalmente, comprime por columna y ocupa una fracción de lo que ocuparía un CSV, y permite leer solo las columnas necesarias, lo que acelera bastante cuando el consumidor pide dos de quince columnas.

Ahora bien, no se descartó el CSV por completo.
Al respecto, se escribe igualmente una copia en CSV del agregado principal, porque es el formato que cualquiera abre en una planilla sin instalar nada, y eso resuelve la mitad de los pedidos que llegan a un equipo de datos.

### PostgreSQL como almacén y dbt encima

Los archivos resuelven la persistencia, pero no resuelven el cruce con otras tablas.
Para eso hace falta SQL, y sobre SQL trabaja dbt.

La división de trabajo es clara.
Python se ocupa de lo que SQL hace mal, es decir, leer archivos, manejar errores de formato y hablar con sistemas externos.
SQL, en cambio, se ocupa de lo que hace mejor que nadie, que consiste en transformar tablas.

### Airflow con ejecutor local

El ejecutor local corre las tareas como procesos hijos del programador.
Para este volumen alcanza de sobra, razón por la que se descartó el ejecutor de Celery, que habría obligado a sumar Redis más trabajadores (dos servicios más para mantener y monitorear).

### Prometheus con Pushgateway

El pipeline es un proceso por lotes y no un servicio web, así que no puede exponer un endpoint que Prometheus consulte.
Para cuando llegara el raspado, el proceso ya terminó.
El Pushgateway resuelve exactamente ese caso, puesto que el trabajo empuja sus métricas al terminar y Prometheus las lee desde ahí.

Toda la capa de métricas está pensada para degradarse sin romper nada.
En caso de que el Pushgateway no responda, las métricas se escriben en el log y la corrida sigue.
Dicho de otro modo, un problema de observabilidad nunca debería tirar abajo un pipeline que produjo datos correctos.

### Cuarentena en vez de descarte

Una fila descartada sin registro es información perdida.
Por ello se descartó el borrado directo, ya que guardar las filas con su motivo permite revisar más tarde si hay que corregir el origen o ajustar la regla, y sobre todo permite responder por qué falta un registro cuando alguien del negocio lo pregunta.

### Configuración centralizada

Ningún módulo arma rutas a mano ni lee variables de entorno por su cuenta, puesto que todo pasa por `trabajos/configuracion.py`.
De ese modo, cuando el pipeline sale de una notebook y entra en un contenedor, solo cambian las variables de entorno y el código queda intacto.

---

## Documentación adicional

| Documento | Contenido |
| --- | --- |
| [Arquitectura](documentacion/arquitectura.md) | Diseño del sistema, capas y decisiones con sus contrapartidas. |
| [Runbook](documentacion/runbook.md) | Guía operativa y resolución de problemas. |
| [Guía de demo](documentacion/guia_demo.md) | Pasos para reproducir el funcionamiento. |
| [Observabilidad](documentacion/observabilidad.md) | Métricas, alertas y tableros. |
| [Integración continua](documentacion/cicd.md) | Etapas del pipeline de CI/CD. |
| [Calidad del código](documentacion/calidad_codigo.md) | Convenciones de escritura y de diseño aplicadas. |

---

## Requisitos

| Herramienta | Versión | Necesaria para |
| --- | --- | --- |
| Python | 3.11 o superior | Ejecución local del pipeline |
| Docker | 24 o superior | Infraestructura completa |
| Docker Compose | v2 | Orquestación de contenedores |
| Make | opcional | Atajos de línea de comandos |

### Memoria

La pila completa funciona con **4 GB asignados a Docker**.
Los once servicios en reposo consumen unos 800 MB, y el pipeline sobre el archivo completo de 1,067,371 filas corre dentro de **1 GB**, cifra verificada ejecutándolo en un contenedor con ese límite estricto.

Conviene precisar que ese número no salió gratis.
La primera versión leía el CSV entero de una vez y moría por falta de memoria incluso con 2 GB.
Por ello, la ingesta ahora lee por lotes y convierte cada uno apenas se lee, de modo que la representación más costosa nunca existe completa (el detalle está en `trabajos/ingesta.py`).

En caso de que aun así una tarea de Airflow termine con código de retorno `-9`, se trata del sistema operativo matando el proceso por falta de memoria, y el runbook explica qué hacer.

Las dependencias quedan fijadas en `requisitos.txt`, con versiones exactas para que cualquiera obtenga el mismo comportamiento.

---

## Licencia

El proyecto se publica bajo licencia MIT.
Por su parte, el conjunto de datos Online Retail II pertenece a sus autores y está disponible bajo licencia Creative Commons Attribution 4.0.
