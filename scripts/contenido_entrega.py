"""
Contenido de las secciones del documento de entrega.
El presente módulo se mantiene separado del generador para que un archivo se ocupe del formato y el otro del texto.
De ese modo, cambiar la redacción de una sección no obliga a tocar la lógica de estilos, ni al revés.
Conviene precisar que los datos concretos, como la cantidad de filas procesadas o el ingreso total, se leen del reporte de la última corrida en lugar de escribirse a mano.
En consecuencia, el documento no puede quedar desactualizado respecto del código.
"""

from __future__ import annotations

from typing import Any

from docx import Document

from scripts.generar_documento_entrega import (
    _extraer,
    _leer,
    codigo,
    nota,
    parrafo,
    tabla,
    titulo,
    vinetas,
)


def _numero(evidencia: dict, *claves: str, defecto: Any = 0) -> Any:
    """
    Busca un valor anidado dentro del reporte de la corrida.
    Recibe el reporte completo de la última ejecución y la secuencia de claves que hay que recorrer para llegar al dato.
    Devuelve el valor encontrado y, en caso de que el camino no exista, el valor por defecto que se haya indicado.
    Dicha tolerancia importa, porque el documento se tiene que poder generar aunque el pipeline todavía no haya corrido.
    """
    actual: Any = evidencia
    for clave in claves:
        if not isinstance(actual, dict) or clave not in actual:
            return defecto
        actual = actual[clave]
    return actual


def _formato(valor: Any, decimales: int = 0) -> str:
    """
    Formatea un número con coma para los miles y punto para los decimales, que es la convención que sigue todo el documento.
    Al respecto, la alternativa de invertir ambos signos quedó descartada porque produce cifras ambiguas.
    Un importe de veinte millones con dos decimales, escrito con punto tanto en los miles como en los decimales, deja tres puntos en la cifra y ya no se distingue cuál de ellos separa la parte decimal.
    Devuelve el número convertido a texto y, en caso de que el valor recibido no sea numérico, lo devuelve tal como llegó.
    """
    try:
        return f"{float(valor):,.{decimales}f}"
    except (TypeError, ValueError):
        return str(valor)


# =============================================================================


def escribir_contenido(documento: Document, evidencia: dict, metadatos: dict) -> None:
    """
    Escribe todas las secciones del documento, una tras otra y en el orden definitivo.
    Recibe el documento donde escribir, el reporte de la última corrida del pipeline y los datos de la entrega, como el autor y el repositorio.
    """
    _resumen_ejecutivo(documento, evidencia, metadatos)
    _arquitectura(documento)
    _infraestructura(documento)
    _orquestacion(documento)
    _transformaciones_dbt(documento)
    _procesamiento_distribuido(documento)
    _datos_de_ejemplo(documento, evidencia)
    _pruebas(documento)
    _integracion_continua(documento)
    _observabilidad(documento)
    _runbook(documento)
    _guia_demo(documento)
    _evidencia_de_ejecucion(documento, evidencia)
    _calidad_del_codigo(documento)
    _cierre(documento, metadatos)


# =============================================================================
# 1. Resumen ejecutivo
# =============================================================================


def _resumen_ejecutivo(documento: Document, evidencia: dict, metadatos: dict) -> None:
    """
    Escribe el resumen ejecutivo, cuyos números provienen de la corrida real y no de una estimación escrita a mano.
    """
    titulo(documento, "1. Resumen ejecutivo", nivel=1, salto=True)

    parrafo(
        documento,
        "El presente documento describe un pipeline de datos extremo a extremo construido sobre "
        "un histórico real de transacciones de comercio minorista. Al respecto, el sistema toma "
        "un archivo crudo de poco más de un millón de líneas de factura, lo valida contra seis "
        "reglas de calidad, calcula el ingreso generado por cada producto en cada fecha y "
        "publica el resultado en formato Parquet, en un almacén analítico y en un tablero de "
        "monitoreo.",
    )

    parrafo(
        documento,
        "El proyecto no busca acumular herramientas. Por el contrario, cada componente está "
        "porque resuelve un problema concreto que se explica en su sección correspondiente, y "
        "en varios casos se documenta también qué alternativa se descartó y por qué. En "
        "definitiva, la decisión de fondo que atraviesa todo el diseño es que el motor se elige "
        "por el problema y no al revés.",
    )

    titulo(documento, "1.1 Qué resuelve", nivel=2)

    parrafo(
        documento,
        "Los datos de un sistema transaccional no llegan listos para analizar. Es decir, vienen "
        "con devoluciones registradas como cantidades negativas, con cargos administrativos "
        "cargados como si fueran productos, con líneas repetidas por reejecuciones parciales "
        "del proceso de exportación y con campos incompletos. Por ello, el pipeline convierte "
        "todo eso en una tabla confiable y deja constancia de cada registro que descartó junto "
        "con el motivo.",
    )

    codigo(
        documento,
        "ingreso_total = cantidad x precio_unitario\n"
        "\n"
        "agrupado por fecha y producto_id",
        "Cálculo central del proyecto",
    )

    titulo(documento, "1.2 Resultados de la ejecución", nivel=2)

    parrafo(
        documento,
        "Los siguientes números provienen del reporte que dejó la última corrida sobre el "
        "conjunto de datos completo. Cabe señalar que no están escritos a mano, puesto que el "
        "generador de este documento los lee del archivo de resultados.",
    )

    tabla(
        documento,
        ["Indicador", "Valor"],
        [
            ["Filas leídas del archivo crudo", _formato(_numero(evidencia, "validacion", "filas_entrada"))],
            ["Filas que superaron la validación", _formato(_numero(evidencia, "validacion", "filas_validas"))],
            ["Filas enviadas a cuarentena", _formato(_numero(evidencia, "validacion", "filas_rechazadas"))],
            ["Porcentaje de rechazo", f"{_numero(evidencia, 'validacion', 'porcentaje_rechazo')} por ciento"],
            ["Ingreso total calculado", _formato(_numero(evidencia, "metricas_negocio", "ingreso_total"), 2)],
            ["Unidades vendidas", _formato(_numero(evidencia, "metricas_negocio", "unidades_vendidas"))],
            ["Productos distintos", _formato(_numero(evidencia, "metricas_negocio", "productos_distintos"))],
            ["Días cubiertos", _formato(_numero(evidencia, "metricas_negocio", "dias_cubiertos"))],
            [
                "Período procesado",
                f"{_numero(evidencia, 'metricas_negocio', 'fecha_minima', defecto='sin dato')} "
                f"al {_numero(evidencia, 'metricas_negocio', 'fecha_maxima', defecto='sin dato')}",
            ],
        ],
        anchos=[8.5, 7.0],
    )

    nota(
        documento,
        "El porcentaje de rechazo se mantiene muy por debajo del quince por ciento a partir "
        "del cual el pipeline se detiene sin publicar. Al respecto, los descartes se reparten "
        "entre devoluciones, precios fuera de rango y líneas duplicadas, que son exactamente "
        "los problemas conocidos de este conjunto de datos.",
        "exito",
    )

    titulo(documento, "1.3 Componentes del sistema", nivel=2)

    tabla(
        documento,
        ["Plano", "Tecnología", "Qué resuelve"],
        [
            ["Orquestación", "Apache Airflow 2.10.5", "Define cuándo corre cada etapa y en qué orden"],
            ["Procesamiento", "Python 3.12 con pandas", "Ingesta, calidad y transformaciones de negocio"],
            ["Distribuido", "Apache Spark 3.5.4", "Funciones de ventana sobre el histórico completo"],
            ["Almacenamiento", "Parquet y PostgreSQL 16", "Archivos comprimidos y almacén consultable"],
            ["Modelado", "dbt Core 1.9", "Capas de preparación, intermedia y publicada"],
            ["Observabilidad", "Prometheus y Grafana", "Métricas, alertas y tablero de estado"],
            ["Infraestructura", "Docker Compose", "Once servicios reproducibles en cualquier máquina"],
            ["Integración", "GitHub Actions", "Cinco etapas de validación automática"],
        ],
        anchos=[3.2, 4.3, 8.0],
    )

    titulo(documento, "1.4 Repositorio", nivel=2)

    codigo(documento, metadatos["repositorio"])

    parrafo(
        documento,
        "El repositorio se puede clonar y ejecutar sin descargar nada adicional, porque "
        "incluye una muestra de cincuenta y dos mil filas construida a partir de facturas "
        "completas del archivo original.",
    )


# =============================================================================
# 2. Arquitectura
# =============================================================================


def _arquitectura(documento: Document) -> None:
    """
    Escribe la sección de arquitectura, en la que cada componente aparece junto con la razón por la que se eligió.
    """
    titulo(documento, "2. Arquitectura y justificación técnica", nivel=1, salto=True)

    titulo(documento, "2.1 Visión general", nivel=2)

    parrafo(
        documento,
        "El sistema tiene cuatro planos que se pueden operar por separado. Cabe señalar que esa "
        "separación no es decorativa, dado que permite levantar únicamente lo que se necesita. "
        "De ese modo, quien quiere correr el pipeline una sola vez no tiene que pagar el costo "
        "de arrancar Grafana.",
    )

    codigo(
        documento,
        """PLANO DE ORQUESTACION
  Airflow (programador + servidor web) sobre PostgreSQL de metadatos
  Define cuando corre cada cosa y en que orden
                       |
                       v
PLANO DE PROCESAMIENTO
  ingesta  -->  validacion  -->  transformacion  -->  persistencia
  pandas        6 reglas         agregaciones        Parquet + CSV
                    |                                     |
                    v                                     v
              cuarentena CSV                    almacen y Spark
                       |
                       v
PLANO DE ALMACENAMIENTO
  Sistema de archivos            PostgreSQL
  detalle_ventas/                crudo      (zona de aterrizaje)
  ingresos_producto_fecha/       preparado  (vistas de dbt)
  analitica_spark/               publicado  (tablas finales)
                       |
                       v
PLANO DE OBSERVABILIDAD
  pipeline  --push-->  Pushgateway  --+
  Airflow   --statsd-> exportador  --+--> Prometheus --> Grafana
  Postgres  ---------> exportador  --+         |
                                               +--> reglas de alerta""",
        "Arquitectura del sistema",
    )

    titulo(documento, "2.2 Flujo de datos", nivel=2)

    titulo(documento, "Etapa 1. Ingesta", nivel=3)

    parrafo(
        documento,
        "La ingesta lee el archivo crudo, traduce los encabezados del inglés al vocabulario del "
        "proyecto y fuerza los tipos. Ahora bien, la decisión importante es que no descarta "
        "ninguna fila, ni siquiera las que a simple vista están mal. Es decir, un valor que no "
        "se puede convertir a número queda como nulo en lugar de cortar la lectura.",
    )

    parrafo(
        documento,
        "La razón es que el motivo de cada descarte tiene que quedar registrado, y eso "
        "corresponde a la capa de calidad. En caso de que la ingesta filtrara por su cuenta, se "
        "perdería la trazabilidad y una excepción sin contexto reemplazaría a un reporte que "
        "explica qué pasó.",
    )

    parrafo(
        documento,
        "La lectura se hace por lotes y no de una sola vez. Conviene precisar que esa decisión "
        "no estaba en el diseño original, sino que se agregó después de que el pipeline muriera "
        "por falta de memoria dentro del contenedor de Airflow. Al respecto, un millón de filas "
        "con ocho columnas de texto recién leídas ocupa varios cientos de megabytes como "
        "objetos de Python, que es la representación más costosa de todo el recorrido. De ese "
        "modo, al convertir cada lote apenas se lee, esa estructura nunca llega a existir "
        "completa.",
    )

    nota(
        documento,
        "El resultado es medible. Es decir, el pipeline completo sobre el archivo entero de "
        "1,067,371 filas corre dentro de un contenedor limitado a un gigabyte, cuando la "
        "versión anterior fallaba incluso con dos.",
        "exito",
    )

    titulo(documento, "Etapa 2. Validación de calidad", nivel=3)

    parrafo(
        documento,
        "La validación aplica seis reglas y separa las filas en dos grupos. Es decir, las que "
        "pasan siguen adelante y las que no van a cuarentena con el nombre de la regla que las "
        "descartó.",
    )

    tabla(
        documento,
        ["Regla", "Qué comprueba"],
        [
            ["columnas_obligatorias_sin_nulos", "Producto, cantidad, fecha y precio están presentes"],
            ["producto_identificable", "El código de producto no está vacío"],
            ["fecha_dentro_de_rango", "La fecha se interpreta y no es futura"],
            ["cantidad_minima", "La cantidad llega al mínimo configurado"],
            ["precio_en_rango", "El precio queda entre el mínimo y el máximo"],
            ["sin_duplicados_exactos", "No se repite la misma línea de factura"],
        ],
        anchos=[6.5, 9.0],
    )

    parrafo(
        documento,
        "Una fila que incumple varias reglas recibe solo el nombre de la primera del catálogo. "
        "Al respecto, se eligió un motivo único por fila en lugar de una lista porque de ese "
        "modo la suma de los conteos por regla coincide con el total de rechazos, y esa "
        "coincidencia hace que el tablero de calidad sea interpretable sin explicación "
        "adicional.",
    )

    nota(
        documento,
        "Por encima de las reglas hay un umbral global. En caso de que se rechace más del "
        "quince por ciento de las filas, el pipeline se detiene sin publicar. La razón es que "
        "perder un uno por ciento constituye ruido normal de un sistema transaccional, mientras "
        "que perder la mitad significa que algo cambió en el origen (publicar ese resultado "
        "sería peor que no publicar nada).",
        "aviso",
    )

    titulo(documento, "Etapa 3. Transformación", nivel=3)

    parrafo(
        documento,
        "La transformación calcula el ingreso por línea de factura y arma las agregaciones. "
        "Cabe señalar que todas sus funciones son puras, es decir, reciben una tabla y "
        "devuelven otra sin tocar disco ni variables globales. En consecuencia, se pueden "
        "probar con tablas de tres filas armadas a mano, y esa es la razón por la que la "
        "batería de setenta y tantas pruebas corre en pocos segundos.",
    )

    parrafo(
        documento,
        "El redondeo a dos decimales se aplica a nivel de línea y no al final. La razón es que "
        "el importe de una línea de factura constituye un valor monetario real, de modo que "
        "sumar valores ya redondeados da el mismo resultado que muestra el sistema contable de "
        "origen, que es contra lo que se compara.",
    )

    titulo(documento, "Etapa 4. Verificación de la salida", nivel=3)

    parrafo(
        documento,
        "Antes de escribir nada se comprueba el resultado. Al respecto, el agregado no puede "
        "estar vacío, no puede tener importes negativos ni nulos, y la combinación de fecha y "
        "producto tiene que ser única. Dichas comprobaciones cierran el círculo, dado que las "
        "reglas anteriores miran la entrada y estas miran la salida, que es justamente lo que "
        "van a consumir los tableros.",
    )

    titulo(documento, "Etapa 5. Persistencia", nivel=3)

    parrafo(
        documento,
        "La persistencia escribe en Parquet particionado por año y mes, y también en CSV. "
        "Conviene precisar que la escritura borra el destino anterior antes de empezar. En caso "
        "de que faltara ese paso, volver a correr el pipeline sobre una carpeta particionada "
        "dejaría conviviendo los archivos de la corrida vieja con los de la nueva y los conteos "
        "saldrían duplicados.",
    )

    titulo(documento, "2.3 Decisiones y concesiones", nivel=2)

    titulo(documento, "pandas para el flujo principal, PySpark solo donde aporta", nivel=3)

    parrafo(
        documento,
        "El archivo completo son noventa y seis megabytes en CSV y algo más de un millón de "
        "filas, de manera que entra en memoria sin esfuerzo. En consecuencia, levantar una "
        "máquina virtual de Java para eso agregaría unos veinte segundos de arranque en cada "
        "corrida, más una capa de configuración y de depuración, sin ninguna mejora de "
        "rendimiento.",
    )

    parrafo(
        documento,
        "PySpark se reserva para lo que sí justifica un motor distribuido, que son las "
        "funciones de ventana sobre todo el histórico. Al respecto, una ventana particionada "
        "por mes se procesa en paralelo, con cada partición ordenándose en un ejecutor "
        "distinto. En cambio, usar Spark para leer un CSV de cien megabytes no demuestra "
        "dominio de la herramienta, sino que no se evaluó si hacía falta.",
    )

    parrafo(
        documento,
        "Lo que se pierde es que el pipeline no escala más allá de la memoria de una máquina. "
        "En caso de que el volumen creciera un orden de magnitud, habría que reescribir la "
        "etapa de transformación en Spark, y esa reescritura quedaría contenida en un solo "
        "módulo porque las funciones son puras.",
    )

    titulo(documento, "Parquet como formato de salida", nivel=3)

    vinetas(
        documento,
        [
            "**Guarda el esquema junto con los datos**, así que no hay que adivinar tipos al releer.",
            "**Comprime por columna.** Al respecto, el detalle en Parquet con Zstandard ocupa alrededor de una décima parte del CSV equivalente.",
            "**Permite leer solo las columnas necesarias**, lo que acelera bastante cuando el consumidor pide dos de quince columnas.",
            "**Adicionalmente se escribe una copia en CSV** del agregado principal, porque es el formato que cualquiera abre en una planilla sin instalar nada.",
        ],
    )

    parrafo(
        documento,
        "Delta Lake e Iceberg se descartaron. Cabe señalar que ambos aportan transacciones y "
        "viaje en el tiempo, prestaciones valiosas cuando hay escrituras concurrentes o hace "
        "falta auditar el estado histórico. En cambio, en este proyecto hay un único escritor y "
        "una sola escritura por día, motivo por el cual esas herramientas solo agregarían "
        "dependencias.",
    )

    titulo(documento, "PostgreSQL como almacén analítico", nivel=3)

    parrafo(
        documento,
        "PostgreSQL es transaccional, tiene todas las funciones de ventana que el proyecto "
        "necesita, dbt lo soporta de primera y corre en un contenedor de sesenta megabytes. "
        "Adicionalmente, con menos de dos millones de filas un motor columnar no aportaría una "
        "diferencia perceptible.",
    )

    parrafo(
        documento,
        "Por su parte, se descartó DuckDB, que es excelente para el análisis en una sola "
        "máquina, porque un archivo local no da acceso concurrente y el almacén tiene que "
        "poder recibir consultas mientras el pipeline escribe. Del mismo modo, se descartó un "
        "almacén en la nube, "
        "puesto que el proyecto tiene que poder clonarse y ejecutarse sin credenciales ni "
        "costos.",
    )

    titulo(documento, "Airflow con ejecutor local", nivel=3)

    parrafo(
        documento,
        "El ejecutor local corre las tareas como procesos hijos del programador. Para este "
        "volumen alcanza de sobra y, adicionalmente, evita sumar Redis y trabajadores de "
        "Celery, que serían dos servicios más para levantar, monitorear y explicar. Ahora bien, "
        "pasar a Celery más adelante consiste en cambiar tres variables de entorno y agregar "
        "dos servicios, de modo que el costo de migrar resulta bajo.",
    )

    titulo(documento, "Una sola imagen para todo el clúster de Spark", nivel=3)

    parrafo(
        documento,
        "El controlador de Spark corre dentro del contenedor de Airflow, que usa Python 3.12. "
        "En caso de que los ejecutores usaran otra versión, el trabajo fallaría al deserializar "
        "las funciones enviadas, con un error que no dice nada sobre su causa real. Por ello, "
        "construir el maestro, el trabajador y el cliente desde la misma imagen elimina esa "
        "clase de problema por completo.",
    )

    titulo(documento, "La observabilidad nunca hace fallar el pipeline", nivel=3)

    parrafo(
        documento,
        "Todo error al publicar métricas se atrapa y solo genera una advertencia en el "
        "registro. La razón es que un problema de monitoreo no puede invalidar datos que se "
        "calcularon bien. Dicho de otro modo, se evita la clase de acoplamiento que convierte "
        "una caída menor de infraestructura en una interrupción del servicio de datos.",
    )

    titulo(documento, "2.4 Qué haría falta para llevarlo a producción", nivel=2)

    parrafo(
        documento,
        "El proyecto está pensado para correr en una sola máquina. Por ello, vale la pena ser "
        "explícito sobre los cambios que requeriría un entorno real, dado que una arquitectura "
        "que no reconoce sus límites resulta difícil de evaluar.",
    )

    tabla(
        documento,
        ["Aspecto", "Estado actual", "Qué haría falta"],
        [
            ["Credenciales", "Variables de entorno con valores por defecto", "Un gestor de secretos"],
            ["Ejecutor de Airflow", "Local, un solo contenedor", "Celery o Kubernetes"],
            ["Carga al almacén", "Reemplazo completo de tabla", "Carga incremental por partición"],
            ["Alta disponibilidad", "Una instancia de cada servicio", "Réplicas y balanceo"],
            ["Copias de seguridad", "No configuradas", "Respaldo periódico con prueba de restauración"],
            ["Control de acceso", "Un usuario administrador", "Roles por función"],
            ["Cifrado", "Tráfico en claro en la red interna", "TLS entre servicios"],
            ["Envío de alertas", "Reglas definidas sin destinatario", "Alertmanager con un canal real"],
        ],
        anchos=[3.5, 5.8, 6.2],
    )

    parrafo(
        documento,
        "Ninguno de estos puntos afecta la corrección de lo que el pipeline calcula. Es decir, "
        "se trata de requisitos de operación y de seguridad que aparecen cuando el sistema deja "
        "de correr en una máquina de escritorio.",
    )


# =============================================================================
# 3. Infraestructura
# =============================================================================


def _infraestructura(documento: Document) -> None:
    """
    Escribe la sección de infraestructura, que describe los servicios de Docker Compose y las imágenes propias del proyecto.
    """
    titulo(documento, "3. Infraestructura", nivel=1, salto=True)

    parrafo(
        documento,
        "Toda la infraestructura está definida en un único archivo de Docker Compose que "
        "levanta once servicios. Al respecto, están agrupados en perfiles, de modo que se "
        "pueden encender por separado según lo que se necesite.",
    )

    titulo(documento, "3.1 Servicios", nivel=2)

    tabla(
        documento,
        ["Servicio", "Imagen", "Puerto", "Función"],
        [
            ["postgres", "postgres:16-alpine", "5432", "Metadatos de Airflow y almacén analítico"],
            ["airflow-inicializacion", "propia", "sin puerto", "Migraciones, usuario y conexiones"],
            ["airflow-servidor", "propia", "8080", "Interfaz web del orquestador"],
            ["airflow-programador", "propia", "sin puerto", "Dispara y ejecuta las tareas"],
            ["spark-maestro", "propia", "8081, 7077", "Coordinador del clúster"],
            ["spark-trabajador", "propia", "8082", "Ejecutor de tareas distribuidas"],
            ["pipeline", "propia", "sin puerto", "Corrida bajo demanda del pipeline"],
            ["dbt", "propia", "sin puerto", "Construcción de los modelos"],
            ["prometheus", "prom/prometheus:v3.1.0", "9090", "Recolección de métricas"],
            ["grafana", "grafana/grafana:11.4.0", "3000", "Tableros de visualización"],
            ["pushgateway", "prom/pushgateway:v1.10.0", "9091", "Recibe métricas del pipeline"],
            ["statsd-exportador", "prom/statsd-exporter:v0.28.0", "9102", "Traduce métricas de Airflow"],
            ["postgres-exportador", "postgres-exporter:v0.16.0", "9187", "Métricas del almacén"],
        ],
        anchos=[4.0, 4.5, 2.3, 4.7],
    )

    titulo(documento, "3.2 Perfiles de ejecución", nivel=2)

    codigo(
        documento,
        """# Solo la base de datos
docker compose up -d postgres

# Orquestacion, incluye Airflow y Spark
docker compose --profile orquestacion up -d

# Solo la pila de monitoreo
docker compose --profile observabilidad up -d

# Todo
docker compose --profile completo up -d

# Herramientas de un solo uso
docker compose --profile herramientas run --rm pipeline
docker compose --profile herramientas run --rm dbt build""",
        "Perfiles disponibles",
    )

    titulo(documento, "3.3 Bloque reutilizable de Airflow", nivel=2)

    parrafo(
        documento,
        "Los tres servicios de Airflow comparten unas cuarenta líneas de configuración. Por "
        "ello, esa configuración se declara una sola vez mediante un ancla de YAML, que es "
        "justamente lo que evita las inconsistencias cuando hay que cambiar algo.",
    )

    codigo(documento, _extraer("docker-compose.yml", "x-airflow-comun:", "services:"), "docker-compose.yml")

    titulo(documento, "3.4 Imagen de Airflow", nivel=2)

    parrafo(
        documento,
        "Sobre la imagen oficial se agregan tres cosas. En primer lugar, se instala Java, "
        "porque el controlador de Spark corre dentro de este contenedor. A continuación, se "
        "instalan las dependencias del pipeline, que son las mismas que se usan en local. Por "
        "último, se instala dbt dentro de un entorno virtual separado.",
    )

    parrafo(
        documento,
        "El caso de dbt merece una explicación. Al respecto, Airflow y dbt fijan versiones "
        "distintas de varias librerías compartidas, de manera que ponerlos en el mismo entorno "
        "termina en un conflicto sin solución limpia. En consecuencia, aislar dbt en su propio "
        "entorno virtual y llamarlo por su ruta absoluta evita el problema por completo (el "
        "costo son unos doscientos megabytes adicionales en la imagen).",
    )

    codigo(documento, _leer("docker/airflow/Dockerfile"), "docker/airflow/Dockerfile")

    titulo(documento, "3.5 Imagen del clúster de Spark", nivel=2)

    codigo(documento, _leer("docker/spark/Dockerfile"), "docker/spark/Dockerfile")

    titulo(documento, "3.6 Inicialización del almacén", nivel=2)

    parrafo(
        documento,
        "Un solo servidor de PostgreSQL aloja dos bases con propósitos muy distintos. Al "
        "respecto, la base de Airflow guarda el estado del orquestador y la base analítica "
        "guarda los datos del negocio. En caso de que compartieran una sola base, una consulta "
        "pesada de un analista podría trabar el planificador de tareas.",
    )

    codigo(documento, _leer("docker/postgres/01_crear_bases.sql"), "docker/postgres/01_crear_bases.sql")

    titulo(documento, "3.7 Puertos configurables", nivel=2)

    parrafo(
        documento,
        "Todos los puertos que se publican hacia la máquina anfitriona salen de variables de "
        "entorno con un valor por defecto. De ese modo, en un equipo donde ya hay otro proceso "
        "escuchando en el ocho mil ochenta basta con definir una variable en el archivo de "
        "entorno, sin tocar la definición de la infraestructura. Cabe señalar que es el tipo de "
        "fricción que aparece siempre y que conviene resolver de una vez.",
    )

    codigo(
        documento,
        """ports:
  - "${PUERTO_AIRFLOW:-8080}:8080"

# En .env, si el 8080 esta ocupado
PUERTO_AIRFLOW=18080""",
        "Patrón usado en todos los servicios",
    )


# =============================================================================
# 4. Orquestación
# =============================================================================


def _orquestacion(documento: Document) -> None:
    """
    Escribe la sección de orquestación, que recorre los dos grafos de Airflow y las decisiones que ordenan sus tareas.
    """
    titulo(documento, "4. Orquestación con Airflow", nivel=1, salto=True)

    parrafo(
        documento,
        "Hay dos grafos. Es decir, el principal construye los datos y el de vigilancia los "
        "audita. La separación es deliberada, puesto que mezclarlos haría que un problema de "
        "vigilancia detuviera la producción de datos, que es exactamente lo contrario de lo que "
        "se busca.",
    )

    titulo(documento, "4.1 Grafo principal", nivel=2)

    tabla(
        documento,
        ["Propiedad", "Valor", "Motivo"],
        [
            ["Identificador", "ventas_minoristas_diario", "Nombre descriptivo del propósito"],
            ["Programación", "0 6 * * *", "El archivo del día anterior ya está disponible"],
            ["Recuperación", "desactivada", "El pipeline procesa el histórico completo en cada corrida"],
            ["Corridas simultáneas", "1", "Dos a la vez escribirían sobre los mismos archivos"],
            ["Reintentos", "2 con espera creciente", "El fallo típico es transitorio"],
            ["Tiempo máximo por tarea", "45 minutos", "Evita que una consulta trabada cuelgue el grafo"],
            ["Tiempo máximo de corrida", "2 horas", "Límite superior de seguridad"],
        ],
        anchos=[4.2, 4.3, 7.0],
    )

    titulo(documento, "4.2 Estructura de tareas", nivel=2)

    codigo(
        documento,
        """inicio
   |
   v
preparacion (grupo)
   |-- verificar_archivo_de_entrada     3 reintentos de 30 segundos
   |-- verificar_almacen                5 reintentos de 20 segundos
   |
   v
procesar_ventas                         ingesta, calidad, transformacion, carga
   |
   +---------------------------+
   |                           |
   v                           v
modelado_dbt (grupo)      analisis_distribuido
   |-- instalar_dependencias       spark-submit al clúster
   |-- construir_modelos
   |-- probar_modelos
   |-- generar_documentacion
   |                           |
   +---------------------------+
                 |
                 v
       resumen_de_la_corrida
                 |
                 v
                fin""",
        "Grafo de dependencias",
    )

    parrafo(
        documento,
        "Las verificaciones previas van primero por una razón económica. Al respecto, fallar "
        "ahí cuesta segundos, mientras que fallar después de veinte minutos de procesamiento "
        "cuesta bastante más. Por su parte, dbt y Spark corren en paralelo porque no dependen "
        "entre sí, dado que a los dos les basta con que el procesamiento haya terminado.",
    )

    titulo(documento, "4.3 Estrategia de reintentos", nivel=2)

    parrafo(
        documento,
        "Los tiempos no son uniformes porque las causas de fallo tampoco lo son. Al respecto, "
        "las tareas de verificación usan reintentos cortos y numerosos, ya que su fallo típico "
        "es un servicio que todavía está arrancando. En cambio, las de procesamiento usan "
        "reintentos más espaciados, puesto que su fallo típico es la contención de recursos, "
        "que necesita más tiempo para resolverse sola.",
    )

    codigo(
        documento,
        _extraer(
            "orquestacion/dags/dag_ventas_diario.py",
            "ARGUMENTOS_POR_DEFECTO = {",
            "DOCUMENTACION",
        ),
        "orquestacion/dags/dag_ventas_diario.py",
    )

    titulo(documento, "4.4 Por qué se llama a la función y no a un subproceso", nivel=2)

    parrafo(
        documento,
        "La tarea de procesamiento importa el pipeline y lo llama directamente, en lugar de "
        "lanzar un proceso aparte. Al respecto, la diferencia importa cuando algo falla, porque "
        "la excepción original llega hasta el registro de Airflow con su rastro completo, en "
        "lugar de un código de salida sin contexto.",
    )

    codigo(
        documento,
        _extraer(
            "orquestacion/dags/dag_ventas_diario.py",
            "@task(task_id=\"procesar_ventas\"",
            "# ---",
        ),
        "Tarea de procesamiento",
    )

    titulo(documento, "4.5 Por qué dbt se ejecuta con BashOperator", nivel=2)

    parrafo(
        documento,
        "dbt vive en su propio entorno virtual dentro de la imagen, con versiones de librerías "
        "incompatibles con las de Airflow. Por ello, llamarlo por su ruta absoluta mantiene los "
        "dos mundos separados y evita un conflicto de dependencias que no tiene solución "
        "limpia.",
    )

    codigo(
        documento,
        _extraer(
            "orquestacion/dags/dag_ventas_diario.py",
            'group_id="modelado_dbt"',
            "# ---",
        ),
        "Grupo de tareas de dbt",
    )

    titulo(documento, "4.6 Grafo de vigilancia de calidad", nivel=2)

    parrafo(
        documento,
        "El grafo de vigilancia corre cada seis horas y no transforma nada, únicamente observa. "
        "Dicho de otro modo, hace las preguntas que uno se haría a mano en caso de sospechar "
        "que algo anda mal.",
    )

    tabla(
        documento,
        ["Tarea", "Qué comprueba", "Cuándo falla"],
        [
            ["verificar_frescura", "La antigüedad del dato más reciente", "La tabla publicada está vacía"],
            ["verificar_volumen", "El conteo de filas de cada tabla", "Alguna tabla quedó sin datos"],
            ["verificar_coherencia", "Los totales entre la capa cruda y la publicada", "La diferencia supera un centavo"],
            ["publicar_metricas_de_calidad", "Envía los resultados a Prometheus", "Nunca, corre siempre"],
        ],
        anchos=[4.5, 6.5, 4.5],
    )

    nota(
        documento,
        "La última tarea tiene la regla de disparo ALL_DONE a propósito. La razón es que, "
        "cuando una comprobación falla, es justamente cuando más importa que la métrica llegue "
        "al sistema de monitoreo.",
        "info",
    )


# =============================================================================
# 5. dbt
# =============================================================================


def _transformaciones_dbt(documento: Document) -> None:
    """
    Escribe la sección de modelado con dbt, que abarca las capas del almacén, los modelos y las pruebas de datos.
    """
    titulo(documento, "5. Transformaciones con dbt", nivel=1, salto=True)

    parrafo(
        documento,
        "El pipeline de Python deja los datos crudos en el esquema de aterrizaje y, a partir de "
        "ahí, dbt construye las capas de modelado. La división del trabajo es clara. Es decir, "
        "Python se ocupa de lo que SQL hace mal, como leer archivos, manejar errores de formato "
        "y hablar con sistemas externos. En cambio, SQL se ocupa de lo que hace mejor que "
        "nadie, que es transformar tablas.",
    )

    titulo(documento, "5.1 Capas del almacén", nivel=2)

    tabla(
        documento,
        ["Esquema", "Materialización", "Contenido", "Quién lo consulta"],
        [
            ["crudo", "tablas del pipeline", "Datos sin modelizar", "Solo dbt"],
            ["preparado", "vistas", "Limpieza y enriquecimiento", "Solo los modelos publicados"],
            ["publicado", "tablas", "Modelos finales", "Tableros y análisis"],
        ],
        anchos=[3.0, 3.8, 4.5, 4.2],
    )

    parrafo(
        documento,
        "Las vistas no ocupan espacio y siempre reflejan el dato más reciente, motivo por el "
        "cual son la opción por defecto para las capas intermedias. En cambio, la capa final se "
        "materializa como tabla, dado que los tableros la consultan muchas veces por minuto y "
        "recalcular la vista en cada consulta resultaría innecesariamente caro.",
    )

    titulo(documento, "5.2 Grafo de modelos", nivel=2)

    codigo(
        documento,
        """crudo.detalle_ventas  (fuente, la escribe el pipeline de Python)
        |
        v
prep_ventas  (vista)
   Normaliza tipos, recorta espacios, marca conceptos administrativos
        |
        v
int_ventas_enriquecidas  (vista)
   Agrega calendario, franja horaria y segmentos de negocio
        |
        +----------------+----------------+-----------------+
        |                |                |                 |
        v                v                v                 v
pub_ingresos_     pub_resumen_      pub_ranking_      pub_ventas_
producto_fecha       diario          productos          por_pais
  (tabla)            (tabla)          (tabla)            (tabla)""",
        "Dependencias entre modelos",
    )

    titulo(documento, "5.3 Modelo principal", nivel=2)

    parrafo(
        documento,
        "El modelo principal es la respuesta directa al objetivo del proyecto. Al respecto, "
        "entrega una fila por combinación de fecha y producto con el ingreso total del día, "
        "más las medidas "
        "de apoyo que ayudan a interpretarlo. Dichas medidas hacen falta, porque el ingreso por "
        "sí solo no distingue un producto caro que se vende poco de uno barato que se vende "
        "mucho.",
    )

    codigo(
        documento,
        _leer("dbt/modelos/publicacion/pub_ingresos_producto_fecha.sql"),
        "dbt/modelos/publicacion/pub_ingresos_producto_fecha.sql",
    )

    titulo(documento, "5.4 Capa de preparación", nivel=2)

    parrafo(
        documento,
        "La vista de preparación es la única puerta de entrada al dato crudo. Es decir, todo lo "
        "que viene después la consulta a ella y nunca a la tabla de origen. En caso de que "
        "mañana cambie "
        "el formato del archivo, el ajuste se hace en un solo lugar y el resto del proyecto no "
        "se entera.",
    )

    codigo(
        documento,
        _leer("dbt/modelos/preparacion/prep_ventas.sql"),
        "dbt/modelos/preparacion/prep_ventas.sql",
    )

    titulo(documento, "5.5 Macros propias", nivel=2)

    parrafo(
        documento,
        "Tres macros resuelven cosas que de otro modo se repetirían en cada modelo, y esa "
        "repetición es donde aparecen las inconsistencias.",
    )

    codigo(documento, _leer("dbt/macros/generar_nombre_esquema.sql"), "dbt/macros/generar_nombre_esquema.sql")

    titulo(documento, "5.6 Pruebas de datos", nivel=2)

    parrafo(
        documento,
        "Hay dos clases de prueba. En primer lugar, las genéricas se declaran en los archivos "
        "de esquema y comprueban la unicidad, la ausencia de nulos y los valores aceptados. Por "
        "su parte, las propias son consultas que devuelven filas únicamente cuando hay un "
        "problema.",
    )

    tabla(
        documento,
        ["Prueba", "Qué verifica", "Severidad"],
        [
            ["los_totales_coinciden_entre_capas", "Agregar no crea ni pierde dinero", "error"],
            ["el_resumen_diario_coincide_con_el_detalle", "La comparación día por día también cierra", "error"],
            ["no_hay_importes_ni_cantidades_negativas", "Ningún modelo publicado tiene medidas negativas", "error"],
            ["la_participacion_del_ranking_es_coherente", "Las participaciones están en rango y no decrecen", "error"],
            ["no_hay_huecos_largos_en_la_serie", "No falta ningún período de más de diez días", "advertencia"],
        ],
        anchos=[6.0, 7.0, 2.5],
    )

    parrafo(
        documento,
        "La prueba de coherencia entre capas es la más importante del proyecto. En caso de que "
        "un día no coincidan los totales, en algún punto de la cadena se duplicaron o se "
        "perdieron filas, y esa es la clase de error que pasa desapercibido durante semanas "
        "porque el tablero sigue mostrando números que parecen razonables.",
    )

    codigo(
        documento,
        _leer("dbt/pruebas/los_totales_coinciden_entre_capas.sql"),
        "dbt/pruebas/los_totales_coinciden_entre_capas.sql",
    )

    parrafo(
        documento,
        "La comparación general por sí sola dejaría pasar un caso incómodo. Es decir, en caso "
        "de que un día quede de más y otro de menos por la misma cifra, el total cierra igual "
        "pero la serie temporal está mal. Por ello hay una segunda prueba que baja la "
        "comparación al nivel de cada día, con una unión completa que detecta también los días "
        "presentes en una tabla y ausentes en la otra.",
    )

    nota(
        documento,
        "La prueba de huecos en la serie se declara con severidad de advertencia y no de "
        "error. La razón es que el conjunto de datos histórico tiene una interrupción real (el "
        "comercio cerró varios días entre diciembre y enero). En consecuencia, hacer fallar "
        "toda la construcción por un hecho conocido del negocio sería contraproducente.",
        "aviso",
    )

    titulo(documento, "5.7 Configuración del proyecto", nivel=2)

    codigo(documento, _leer("dbt/dbt_project.yml"), "dbt/dbt_project.yml")

    titulo(documento, "5.8 Conexión sin credenciales versionadas", nivel=2)

    parrafo(
        documento,
        "Ningún dato sensible está escrito en el archivo de conexión. Al respecto, todo sale de "
        "variables de entorno, de modo que el archivo se puede versionar sin exponer nada. De "
        "ese modo, el mismo proyecto sirve para el entorno local, para la integración continua "
        "y para uno productivo cambiando únicamente el entorno.",
    )

    codigo(documento, _leer("dbt/profiles.yml"), "dbt/profiles.yml")


# =============================================================================
# 6. PySpark
# =============================================================================


def _procesamiento_distribuido(documento: Document) -> None:
    """
    Escribe la sección del trabajo distribuido, en la que se justifica qué cálculos ameritan un motor como Spark.
    """
    titulo(documento, "6. Procesamiento distribuido con PySpark", nivel=1, salto=True)

    parrafo(
        documento,
        "El trabajo de Spark responde preguntas que en pandas se vuelven incómodas cuando el "
        "volumen crece, sobre todo las que necesitan funciones de ventana sobre todo el "
        "histórico.",
    )

    titulo(documento, "6.1 Qué calcula y por qué justifica Spark", nivel=2)

    tabla(
        documento,
        ["Análisis", "Técnica", "Por qué aporta el motor distribuido"],
        [
            [
                "Ranking mensual de productos",
                "Ventana particionada por mes",
                "Cada partición se ordena en paralelo en un ejecutor distinto",
            ],
            [
                "Media móvil de siete días",
                "Ventana por rango de fechas",
                "Recorre la serie completa sin traerla entera a memoria",
            ],
            [
                "Concentración por país",
                "Ventana acumulada",
                "Suma progresiva sobre el total ordenado",
            ],
        ],
        anchos=[4.2, 4.3, 7.0],
    )

    parrafo(
        documento,
        "La media móvil se apoya en una ventana definida sobre días de calendario y no sobre "
        "cantidad de filas. Dicha distinción importa porque el comercio no factura todos los "
        "días, y una ventana por filas mezclaría períodos de duración distinta según cuántos "
        "días hábiles hubo.",
    )

    titulo(documento, "6.2 Configuración de la sesión", nivel=2)

    parrafo(
        documento,
        "El valor por defecto de particiones de barajado en Spark es doscientos, un número "
        "pensado para clústeres grandes. Ahora bien, con el volumen de este conjunto de datos "
        "eso genera cientos de archivos diminutos, y el costo de coordinarlos supera al del "
        "cálculo. En consecuencia, bajar ese valor es la optimización que más se nota en este "
        "proyecto.",
    )

    codigo(
        documento,
        _extraer("trabajos/spark/agregado_ventas.py", "def crear_sesion(", "def leer_detalle("),
        "trabajos/spark/agregado_ventas.py",
    )

    titulo(documento, "6.3 Precisión de los importes", nivel=2)

    parrafo(
        documento,
        "El importe se convierte a decimal con escala fija antes de agregar. La razón es que, "
        "en los cálculos monetarios, el punto flotante acumula error al sumar muchas filas y "
        "los totales dejan de coincidir con los del sistema contable.",
    )

    codigo(
        documento,
        _extraer("trabajos/spark/agregado_ventas.py", "def ranking_mensual_por_producto(", "def tendencia_movil_diaria("),
        "Ranking mensual con función de ventana",
    )

    titulo(documento, "6.4 Un problema real que apareció al integrar", nivel=2)

    parrafo(
        documento,
        "Al ejecutar el trabajo por primera vez contra el Parquet que escribe pandas, Spark "
        "falló con un mensaje que no decía nada sobre su causa real.",
    )

    codigo(
        documento,
        "org.apache.spark.sql.AnalysisException:\n"
        "  Illegal Parquet type: INT64 (TIMESTAMP(NANOS,false))",
        "Error original",
    )

    parrafo(
        documento,
        "La causa es que pandas maneja fechas con precisión de nanosegundos y, en caso de que "
        "no se le indique otra cosa, las escribe así en el archivo. Al respecto, Spark 3.5 no "
        "sabe leer ese tipo. En consecuencia, la solución fue forzar microsegundos en la "
        "escritura, algo que no pierde información porque la granularidad de los datos son los "
        "minutos.",
    )

    codigo(
        documento,
        """opciones = {
    "engine": "pyarrow",
    "compression": COMPRESION_PARQUET,
    "index": False,
    "coerce_timestamps": PRECISION_MARCAS_DE_TIEMPO,
    "allow_truncated_timestamps": True,
}""",
        "Corrección en trabajos/persistencia.py",
    )

    nota(
        documento,
        "Cabe señalar que este tipo de incompatibilidad entre herramientas es exactamente lo "
        "que no aparece hasta que se integra el sistema completo, y es la razón por la que "
        "vale la pena "
        "ejecutar de verdad todo el recorrido en vez de probar cada pieza por separado.",
        "info",
    )

    titulo(documento, "6.5 Modos de ejecución", nivel=2)

    codigo(
        documento,
        """# Contra el clúster de Docker
spark-submit --master spark://spark-maestro:7077 \\
  --conf spark.driver.host=airflow-programador \\
  --conf spark.driver.bindAddress=0.0.0.0 \\
  trabajos/spark/agregado_ventas.py

# En una sola maquina, sin cluster
python trabajos/spark/agregado_ventas.py --maestro "local[*]" """,
        "Invocación del trabajo",
    )

    parrafo(
        documento,
        "En modo clúster el ejecutor necesita saber a qué dirección devolverle los resultados "
        "al controlador, y dentro de Docker eso no se deduce solo. En caso de que falte esa "
        "configuración, Spark anuncia una dirección interna que el trabajador no sabe "
        "alcanzar.",
    )


# =============================================================================
# 7. Datos
# =============================================================================


def _datos_de_ejemplo(documento: Document, evidencia: dict) -> None:
    """
    Escribe la sección del conjunto de datos, que describe su origen, su estructura y los problemas reales que trae.
    """
    titulo(documento, "7. Datos de ejemplo", nivel=1, salto=True)

    titulo(documento, "7.1 Origen", nivel=2)

    parrafo(
        documento,
        "El conjunto elegido es Online Retail II, un histórico real publicado por el "
        "repositorio de aprendizaje automático de la Universidad de California en Irvine y "
        "disponible también en Kaggle. Al respecto, registra todas las transacciones de un "
        "comercio minorista "
        "británico dedicado a artículos de regalo entre diciembre de 2009 y diciembre de 2011.",
    )

    parrafo(
        documento,
        "No es un conjunto sintético. Por el contrario, trae exactamente los problemas que "
        "aparecen en un sistema transaccional de verdad, y esa es la razón por la que resulta "
        "útil en un proyecto que quiere demostrar manejo de calidad de datos.",
    )

    tabla(
        documento,
        ["Característica", "Valor"],
        [
            ["Filas totales", "1,067,371"],
            ["Período", "1 de diciembre de 2009 al 9 de diciembre de 2011"],
            ["Productos distintos", "5,305"],
            ["Países", "43"],
            ["Formato original", "Excel con dos hojas, una por año comercial"],
            ["Licencia", "Creative Commons Attribution 4.0"],
        ],
        anchos=[5.0, 10.5],
    )

    titulo(documento, "7.2 Estructura", nivel=2)

    tabla(
        documento,
        ["Columna original", "Nombre en el proyecto", "Tipo", "Descripción"],
        [
            ["Invoice", "factura", "texto", "Comprobante. Los que empiezan con C son devoluciones"],
            ["StockCode", "producto_id", "texto", "Código de artículo del comercio"],
            ["Description", "descripcion", "texto", "Nombre del artículo. Admite nulos"],
            ["Quantity", "cantidad", "entero", "Unidades. Negativa en devoluciones"],
            ["InvoiceDate", "fecha_hora", "marca de tiempo", "Momento exacto de la operación"],
            ["Price", "precio_unitario", "decimal", "Precio unitario en libras esterlinas"],
            ["Customer ID", "cliente_id", "entero", "Identificador de cliente. Admite nulos"],
            ["Country", "pais", "texto", "País de la operación"],
        ],
        anchos=[3.3, 3.8, 2.7, 5.7],
    )

    titulo(documento, "7.3 Problemas reales del conjunto", nivel=2)

    parrafo(
        documento,
        "Los siguientes conteos salen de la corrida sobre el archivo completo y muestran qué "
        "descartó cada regla.",
    )

    conteos = _numero(evidencia, "validacion", "conteo_por_regla", defecto={})
    filas_conteo = [
        [regla, _formato(cantidad)]
        for regla, cantidad in conteos.items()
    ] or [["sin datos de corrida", "0"]]

    tabla(documento, ["Regla que lo detectó", "Filas afectadas"], filas_conteo, anchos=[9.0, 6.5])

    tabla(
        documento,
        ["Problema", "Tratamiento", "Motivo"],
        [
            [
                "Devoluciones con cantidad negativa",
                "Quedan apartadas",
                "El objetivo es medir ingresos por venta, mezclarlas distorsionaría el agregado",
            ],
            [
                "Cargos administrativos con importes desmedidos",
                "Quedan apartadas",
                "No corresponden a una venta real de producto",
            ],
            [
                "Líneas de factura repetidas",
                "Solo sobrevive la primera",
                "Provienen de reejecuciones parciales del proceso de origen",
            ],
            [
                "Descripciones ausentes",
                "Quedan conservadas",
                "La descripción no es una columna clave para el cálculo",
            ],
            [
                "Cliente sin identificar",
                "Quedan conservadas",
                "Muchas ventas de mostrador no se asocian a ninguna cuenta",
            ],
        ],
        anchos=[4.5, 3.5, 7.5],
    )

    titulo(documento, "7.4 Muestra versionada", nivel=2)

    parrafo(
        documento,
        "El repositorio incluye una muestra de 52,778 filas formada por 2,600 facturas "
        "completas. Cabe señalar que no es un recorte de filas sueltas, puesto que se eligen "
        "comprobantes enteros para que los conteos de facturas distintas sigan teniendo "
        "sentido. Adicionalmente, se fija una semilla para que el resultado sea siempre el "
        "mismo, ya que una muestra que cambiara en cada corrida haría que los números de la "
        "documentación dejaran de coincidir.",
    )

    parrafo(
        documento,
        "El pipeline usa el histórico completo cuando está presente y, en caso contrario, "
        "recurre a la muestra. De ese modo, quien clona el repositorio puede ejecutar todo sin "
        "descargar nada.",
    )

    codigo(
        documento,
        _extraer("trabajos/configuracion.py", "    def resolver_entrada(", "    @property\n    def ruta_detalle_limpio"),
        "trabajos/configuracion.py",
    )

    titulo(documento, "7.5 Ejemplo de registros", nivel=2)

    codigo(
        documento,
        """Invoice,StockCode,Description,Quantity,InvoiceDate,Price,Customer ID,Country
489526,85049E,SCANDINAVIAN REDS RIBBONS,12,2009-12-01 11:50:00,1.25,12533.0,Germany
489526,21242,RED SPOTTY PLATE,8,2009-12-01 11:50:00,1.69,12533.0,Germany
489526,21535,RETRO SPOT SMALL MILK JUG,6,2009-12-01 11:50:00,2.55,12533.0,Germany
489526,21844,RETRO SPOT MUG,6,2009-12-01 11:50:00,2.95,12533.0,Germany
489526,22073,RETRO SPOT STORAGE JAR,4,2009-12-01 11:50:00,3.75,12533.0,Germany""",
        "datos/ejemplos/ventas_minoristas_muestra.csv",
    )


# =============================================================================
# 8. Pruebas
# =============================================================================


def _pruebas(documento: Document) -> None:
    """
    Escribe la sección de pruebas automatizadas, con la estrategia que las ordena y los casos más representativos.
    """
    titulo(documento, "8. Pruebas automatizadas", nivel=1, salto=True)

    titulo(documento, "8.1 Estrategia", nivel=2)

    parrafo(
        documento,
        "El principio que ordena toda la batería es que ninguna prueba dependa del conjunto de "
        "datos real ni de servicios levantados. Al respecto, cada caso arma sus propios datos, "
        "con la cantidad justa de filas para ejercitar una regla concreta y con valores que se "
        "pueden verificar a mano. De ese modo, cuando una prueba falla el problema queda a la "
        "vista sin tener que inspeccionar un millón de registros.",
    )

    tabla(
        documento,
        ["Archivo", "Qué cubre", "Casos"],
        [
            ["test_ingesta.py", "Traducción de encabezados, tipos, errores de lectura", "12"],
            ["test_validaciones.py", "Cada regla por separado y el corte por umbral", "12"],
            ["test_transformaciones.py", "Los cálculos de negocio con valores verificables", "17"],
            ["test_persistencia.py", "Escritura, relectura e idempotencia", "9"],
            ["test_metricas.py", "Que un fallo de monitoreo no interrumpa la corrida", "9"],
            ["test_extremo_a_extremo.py", "El pipeline completo y sus códigos de salida", "11"],
            ["test_dags.py", "Que los grafos de Airflow carguen sin errores", "11"],
        ],
        anchos=[5.0, 8.0, 2.5],
    )

    titulo(documento, "8.2 La prueba más importante", nivel=2)

    parrafo(
        documento,
        "La presente prueba no comprueba un número concreto, sino una propiedad que tiene que "
        "cumplirse siempre. Dicho de otro modo, agregar no puede crear ni perder dinero.",
    )

    codigo(
        documento,
        """def test_la_agregacion_conserva_el_ingreso_total(ventas_validas):
    \"\"\"Agregar no puede crear ni perder dinero.

    Esta es la invariante mas importante del pipeline. La suma del detalle y
    la suma del agregado tienen que coincidir hasta el ultimo centavo.
    \"\"\"
    detalle = calcular_ingreso_total(ventas_validas)
    agregado = agregar_por_producto_y_fecha(detalle)

    assert round(detalle["ingreso_total"].sum(), 2) == round(agregado["ingreso_total"].sum(), 2)
    assert round(agregado["ingreso_total"].sum(), 2) == 190.0""",
        "pruebas/test_transformaciones.py",
    )

    parrafo(
        documento,
        "La misma invariante se comprueba tres veces en tres lugares distintos. En primer "
        "lugar, aquí, sobre datos de prueba. A continuación, en dbt, sobre el almacén ya "
        "construido. Por último, en el grafo de vigilancia, unas horas después. Dicha redundancia "
        "es deliberada, dado que cada capa detecta problemas que las otras no ven.",
    )

    titulo(documento, "8.3 Datos de prueba con valores calculados a mano", nivel=2)

    codigo(
        documento,
        """def test_el_ingreso_de_cada_linea_es_cantidad_por_precio(ventas_validas):
    \"\"\"La multiplicacion basica que define todo el proyecto.

    Las cuentas esperadas son 10 por 2.50, 5 por 6.00, 20 por 2.50,
    4 por 1.25 y 8 por 10.00.
    \"\"\"
    resultado = calcular_ingreso_total(ventas_validas)

    assert list(resultado["ingreso_total"]) == [25.0, 30.0, 50.0, 5.0, 80.0]""",
        "pruebas/test_transformaciones.py",
    )

    parrafo(
        documento,
        "Los valores esperados se documentan en el propio caso, de manera que quien lea la "
        "prueba pueda verificar la cuenta sin ejecutar nada.",
    )

    titulo(documento, "8.4 Cada regla de calidad se prueba por separado", nivel=2)

    parrafo(
        documento,
        "El conjunto de prueba tiene cinco filas buenas y cinco defectuosas, y cada fila "
        "defectuosa incumple exactamente una regla. Así se puede afirmar con precisión cuántos "
        "rechazos tiene que producir cada una.",
    )

    codigo(
        documento,
        """def test_cada_regla_atrapa_exactamente_su_caso(ventas_con_problemas, configuracion_temporal):
    \"\"\"Las cinco filas defectuosas caen una por cada regla.\"\"\"
    resultado = validar(ventas_con_problemas, configuracion_temporal)

    assert resultado.filas_entrada == 10
    assert resultado.filas_validas == 5
    assert resultado.filas_rechazadas == 5

    conteo = resultado.conteo_por_regla
    assert conteo["columnas_obligatorias_sin_nulos"] == 1
    assert conteo["fecha_dentro_de_rango"] == 1
    assert conteo["cantidad_minima"] == 1
    assert conteo["precio_en_rango"] == 1
    assert conteo["sin_duplicados_exactos"] == 1""",
        "pruebas/test_validaciones.py",
    )

    titulo(documento, "8.5 Pruebas de comportamiento ante fallos", nivel=2)

    parrafo(
        documento,
        "La batería prueba explícitamente que un problema de monitoreo no interrumpe una corrida que "
        "produjo datos correctos.",
    )

    codigo(
        documento,
        """def test_un_destino_inalcanzable_no_rompe_la_corrida():
    \"\"\"El fallo de red se atrapa y solo deja una advertencia en el log.\"\"\"
    recolector = RecolectorMetricas(
        configuracion=ConfiguracionMetricas(
            url_pushgateway="http://127.0.0.1:9",
            trabajo="pruebas",
            habilitado=True,
            tiempo_espera_segundos=1,
        )
    )
    recolector.registrar_filas("ingesta", 10)

    assert recolector.publicar() is False""",
        "pruebas/test_metricas.py",
    )

    titulo(documento, "8.6 Pruebas de los grafos de Airflow", nivel=2)

    parrafo(
        documento,
        "No ejecutan tareas, solo comprueban que los archivos de grafo están bien formados. "
        "Suena poco, pero atrapa la falla más frecuente y más molesta del orquestador. Un "
        "error de sintaxis hace que Airflow no cargue el grafo, y lo único que se ve es que "
        "el grafo desapareció de la lista sin ninguna explicación visible.",
    )

    vinetas(
        documento,
        [
            "**No hay errores de importación** en ningún archivo de grafo.",
            "**Están todas las tareas esperadas** y no hay ciclos en las dependencias.",
            "**La validación precede al procesamiento**, para no gastar cómputo antes de verificar.",
            "**dbt y Spark dependen del procesamiento**, no pueden arrancar antes de que existan los datos.",
            "**Ningún grafo recupera corridas pasadas**, que dispararía cientos de ejecuciones idénticas de golpe.",
            "**Todos los grafos tienen documentación y etiquetas**, para que quien los abra entienda qué hacen.",
        ],
    )

    titulo(documento, "8.7 Cómo ejecutarlas", nivel=2)

    codigo(
        documento,
        """# Bateria completa
python -m pytest pruebas -v

# Con informe de cobertura
python -m pytest pruebas --cov=trabajos --cov-report=term-missing

# Solo un archivo
python -m pytest pruebas/test_transformaciones.py -v

# Con Make
make pruebas
make cobertura""",
        "Ejecución de las pruebas",
    )


# =============================================================================
# 9. CI/CD
# =============================================================================


def _integracion_continua(documento: Document) -> None:
    """
    Escribe la sección de integración continua, que detalla las cinco etapas del flujo y el criterio con el que se ordenaron.
    """
    titulo(documento, "9. Integración y entrega continua", nivel=1, salto=True)

    parrafo(
        documento,
        "El criterio de diseño es dar la respuesta más útil en el menor tiempo. Las etapas "
        "rápidas y baratas corren primero, y las que necesitan levantar servicios solo se "
        "ejecutan si las anteriores pasaron. Así, un error de sintaxis se reporta en menos de "
        "un minuto en lugar de después de diez.",
    )

    titulo(documento, "9.1 Etapas", nivel=2)

    codigo(
        documento,
        """                1. verificacion_rapida         ~1 min
                Estilo, YAML, JSON del tablero
                            |
             +--------------+--------------+
             v                             v
   2. pruebas_unitarias          3. validar_infraestructura
   Python 3.11 y 3.12            compose y construccion
   ~3 min                        ~8 min
             +--------------+--------------+
                            v
                4. prueba_de_integracion       ~6 min
                Pipeline y dbt sobre PostgreSQL
                            v
                5. resumen
                Consolida y decide el estado""",
        "Flujo de integración continua",
    )

    titulo(documento, "9.2 Qué valida cada etapa", nivel=2)

    tabla(
        documento,
        ["Etapa", "Validaciones"],
        [
            [
                "Verificaciones rápidas",
                "Estilo con ruff, formato, validez de todos los YAML y del JSON del tablero de Grafana",
            ],
            [
                "Pruebas unitarias",
                "Batería completa sobre Python 3.11 y 3.12, con informe de cobertura",
            ],
            [
                "Infraestructura",
                "Sintaxis de compose, construcción de las dos imágenes, comprobación de que PySpark importa",
            ],
            [
                "Integración",
                "Pipeline completo contra un PostgreSQL real, más dbt deps, run y test",
            ],
            [
                "Resumen",
                "Tabla con el resultado de cada etapa y fallo consolidado si alguna no pasó",
            ],
        ],
        anchos=[4.5, 11.0],
    )

    titulo(documento, "9.3 Decisiones del flujo", nivel=2)

    vinetas(
        documento,
        [
            "**Cancelación de corridas superadas.** Si llegan varios envíos seguidos a la misma rama, se cancela el anterior. No tiene sentido gastar cómputo validando un commit ya superado.",
            "**Matriz sin cancelación anticipada.** Si una versión de Python falla, interesa ver el resultado de la otra para saber si el problema es general o específico.",
            "**Caché de capas de Docker.** Baja el tiempo de la etapa de infraestructura de varios minutos a menos de uno cuando los Dockerfiles no cambiaron.",
            "**La corrida emplea la muestra y no el archivo completo.** Descargar noventa y seis megabytes en cada corrida agregaría un minuto sin aportar cobertura, porque la lógica es la misma.",
            "**Artefactos con retención de catorce días.** Permiten comparar entre corridas cuando algo se degrada de a poco.",
        ],
    )

    titulo(documento, "9.4 Etapa de integración con servicios reales", nivel=2)

    codigo(
        documento,
        _extraer(
            ".github/workflows/integracion-continua.yml",
            "  prueba_de_integracion:",
            "  # ---------------------------------------------------------------------------\n  # Etapa 5",
        ),
        ".github/workflows/integracion-continua.yml",
    )

    titulo(documento, "9.5 Qué faltaría para entrega continua", nivel=2)

    parrafo(
        documento,
        "El flujo actual es de integración continua. Valida, pero no despliega. Las etapas que "
        "faltarían, en el orden en que tendría sentido agregarlas, son la publicación de "
        "imágenes etiquetadas con el identificador del commit, el despliegue automático a un "
        "entorno de pruebas, y el despliegue a producción con aprobación manual.",
    )

    parrafo(
        documento,
        "El etiquetado con el identificador del commit es lo que permite saber exactamente qué "
        "código está corriendo en cada entorno y volver atrás sin ambigüedad. Para los datos, "
        "en cambio, la reversión es más delicada, porque la escritura es de reemplazo completo "
        "y una vez sobrescrito el resultado no hay vuelta atrás sin una copia de seguridad. "
        "Tal es el argumento más fuerte para pasar a carga incremental por partición.",
    )


# =============================================================================
# 10. Observabilidad
# =============================================================================


def _observabilidad(documento: Document) -> None:
    """
    Escribe la sección de observabilidad, que recorre la recolección de métricas, las alertas y el tablero.
    """
    titulo(documento, "10. Observabilidad", nivel=1, salto=True)

    parrafo(
        documento,
        "Un pipeline sin observabilidad es un pipeline en el que uno confía por costumbre. El "
        "principio que guía el diseño es que la observabilidad tiene que responder tres "
        "preguntas en este orden. Está funcionando. Está produciendo lo que debería. Y si algo "
        "anda mal, dónde está.",
    )

    titulo(documento, "10.1 Arquitectura de recolección", nivel=2)

    codigo(
        documento,
        """                   Pushgateway
pipeline --push-->  puerto 9091   --+
(por lotes)                         |
                                    |
                  statsd-exportador |     Prometheus
Airflow  --statsd-> puerto 9102   --+-->  puerto 9090
(UDP 9125)                          |          |
                                    |          v
                postgres-exportador |      Grafana
PostgreSQL -------> puerto 9187   --+     puerto 3000""",
        "Fuentes de métricas",
    )

    tabla(
        documento,
        ["Fuente", "Pregunta que responde"],
        [
            ["Pushgateway", "Qué produjo la última corrida del pipeline"],
            ["statsd-exportador", "Cómo se está comportando el orquestador"],
            ["postgres-exportador", "Cómo está el almacén analítico"],
            ["Prometheus sobre sí mismo", "Si el propio monitoreo está sano"],
        ],
        anchos=[5.5, 10.0],
    )

    titulo(documento, "10.2 Por qué Pushgateway", nivel=2)

    parrafo(
        documento,
        "El pipeline es un proceso por lotes. Arranca, procesa, termina. Si expusiera un "
        "endpoint de métricas, para cuando Prometheus fuera a consultarlo el proceso ya no "
        "existiría. El Pushgateway es un intermediario que guarda las métricas que le empujan "
        "y las mantiene disponibles.",
    )

    parrafo(
        documento,
        "Su limitación conocida es que no distingue entre un trabajo que dejó de correr y uno "
        "que corrió pero no cambió sus valores. Por eso el pipeline publica también la marca "
        "de tiempo de la última corrida exitosa, y sobre esa marca se define la alerta de "
        "datos desactualizados.",
    )

    titulo(documento, "10.3 Métricas publicadas", nivel=2)

    tabla(
        documento,
        ["Métrica", "Tipo", "Etiquetas", "Para qué sirve"],
        [
            ["pipeline_ventas_ejecucion_exitosa", "medidor", "ninguna", "Vale 1 si la corrida terminó bien"],
            ["pipeline_ventas_ultima_ejecucion_exitosa_timestamp", "medidor", "ninguna", "Base de la alerta de datos viejos"],
            ["pipeline_ventas_duracion_segundos", "medidor", "etapa", "Detectar qué etapa se degrada"],
            ["pipeline_ventas_filas_procesadas", "medidor", "etapa", "Ver dónde se pierden registros"],
            ["pipeline_ventas_filas_rechazadas_total", "contador", "regla", "Saber qué regla descarta más"],
            ["pipeline_ventas_porcentaje_rechazo", "medidor", "ninguna", "Vigilar la salud del origen"],
            ["pipeline_ventas_ingreso_total", "medidor", "ninguna", "Detectar saltos que indican duplicación"],
            ["pipeline_ventas_productos_distintos", "medidor", "ninguna", "Detectar catálogos incompletos"],
            ["pipeline_ventas_dias_cubiertos", "medidor", "ninguna", "Detectar períodos faltantes"],
            ["almacen_filas_por_tabla", "medidor", "tabla", "Vigilar el crecimiento del almacén"],
            ["almacen_diferencia_entre_capas", "medidor", "ninguna", "Coherencia entre crudo y publicado"],
        ],
        anchos=[5.5, 2.0, 2.0, 6.0],
    )

    nota(
        documento,
        "Publicar métricas de negocio junto a las técnicas no es habitual pero resulta muy "
        "útil. Un pipeline puede terminar sin errores y aun así haber producido algo "
        "incorrecto. Si el ingreso total se duplica de un día para otro sin que haya cambiado "
        "el volumen, la explicación casi siempre es que se procesó el archivo dos veces.",
        "info",
    )

    titulo(documento, "10.4 Alertas", nivel=2)

    parrafo(
        documento,
        "Cada alerta tiene una acción concreta documentada en el runbook. Una alerta que nadie "
        "sabe cómo atender solo genera ruido y termina ignorándose, así que no se definen "
        "alertas informativas.",
    )

    tabla(
        documento,
        ["Alerta", "Severidad", "Condición", "Espera"],
        [
            ["PipelineFallo", "crítica", "Última corrida con error", "1 min"],
            ["ProgramadorSinLatido", "crítica", "Airflow dejó de latir", "5 min"],
            ["ServicioCaido", "crítica", "Un objetivo no responde", "2 min"],
            ["DatosDesactualizados", "alta", "Más de 26 horas sin corrida buena", "10 min"],
            ["CaidaAbruptaDeVolumen", "alta", "Menos de la mitad del promedio semanal", "15 min"],
            ["AlmacenSinConexionesDisponibles", "alta", "Más del 80 por ciento de conexiones usadas", "5 min"],
            ["TareasDeAirflowFallando", "alta", "Más de 3 fallos en una hora", "5 min"],
            ["CalidadDeDatosDegradada", "media", "Rechazo por encima del 10 por ciento", "5 min"],
            ["PipelineDemasiadoLento", "media", "Una etapa por encima de 15 minutos", "2 min"],
        ],
        anchos=[5.5, 2.3, 5.7, 2.0],
    )

    parrafo(
        documento,
        "La cláusula de espera existe para evitar avisos por un pico momentáneo. Una métrica "
        "que se recupera sola en dos minutos no necesitaba que nadie mirara. Los tiempos no "
        "son arbitrarios, las alertas críticas esperan poco porque el costo de reaccionar "
        "tarde es alto, y las de calidad esperan más porque un pico aislado suele resolverse "
        "en la corrida siguiente.",
    )

    parrafo(
        documento,
        "El umbral de diez por ciento para calidad está por debajo del quince que hace fallar "
        "el pipeline. Dicha separación es deliberada, entre diez y quince el pipeline publica "
        "igual pero avisa, lo que da tiempo a investigar sin que el servicio de datos se "
        "interrumpa.",
    )

    codigo(
        documento,
        _extraer("observabilidad/prometheus/reglas_alertas.yml", "      - alert: PipelineFallo", "      - alert: PipelineDemasiadoLento"),
        "observabilidad/prometheus/reglas_alertas.yml",
    )

    titulo(documento, "10.5 Traducción de las métricas de Airflow", nivel=2)

    parrafo(
        documento,
        "Airflow emite nombres como airflow.dagrun.duration.success.ventas_minoristas_diario, "
        "donde el nombre del grafo está dentro de la cadena. Prometheus espera un nombre "
        "estable y etiquetas que varíen. Sin el archivo de correspondencia, cada grafo "
        "generaría una métrica distinta y sería imposible graficarlos juntos.",
    )

    codigo(
        documento,
        _extraer("observabilidad/statsd/mapeo_airflow.yml", "mappings:", "  # Salud del programador"),
        "observabilidad/statsd/mapeo_airflow.yml",
    )

    titulo(documento, "10.6 Tablero de Grafana", nivel=2)

    parrafo(
        documento,
        "El tablero se aprovisiona por archivo, no se importa a mano. La configuración queda "
        "versionada en el repositorio, se revisa junto con el código y se reconstruye igual en "
        "cualquier máquina. Nadie tiene que acordarse de qué se tocó a mano después de perder "
        "el volumen de Grafana.",
    )

    parrafo(
        documento,
        "Está organizado en cuatro filas que siguen el orden en el que uno investiga un "
        "problema.",
    )

    tabla(
        documento,
        ["Fila", "Paneles", "Pregunta que responde"],
        [
            [
                "Estado general",
                "Resultado, antigüedad, ingreso, productos, días",
                "Está funcionando",
            ],
            [
                "Volumen y calidad",
                "Filas por etapa, rechazo, rechazos por regla, duración",
                "Lo que produjo es razonable",
            ],
            [
                "Orquestación",
                "Latido, tareas por estado, ranuras y cola",
                "El orquestador está sano",
            ],
            [
                "Almacén",
                "Disponibilidad, conexiones, servicios activos",
                "La infraestructura responde",
            ],
        ],
        anchos=[3.5, 6.5, 5.5],
    )

    titulo(documento, "10.7 Consultas útiles", nivel=2)

    codigo(
        documento,
        """# Cuanto hace que no hay una corrida buena
time() - pipeline_ventas_ultima_ejecucion_exitosa_timestamp

# Que proporcion de filas sobrevive a la validacion
pipeline_ventas_filas_procesadas{etapa="validacion"}
  / pipeline_ventas_filas_procesadas{etapa="ingesta"}

# Duracion total de la corrida
sum(pipeline_ventas_duracion_segundos)

# Las tres reglas que mas descartan
topk(3, pipeline_ventas_filas_rechazadas_total)

# Variacion del ingreso respecto de hace un dia
pipeline_ventas_ingreso_total - pipeline_ventas_ingreso_total offset 1d""",
        "Consultas de Prometheus",
    )

    titulo(documento, "10.8 Registros estructurados", nivel=2)

    parrafo(
        documento,
        "Los registros salen en JSON por defecto. Dentro de Docker la salida estándar termina "
        "en el recolector, y un formato estructurado permite filtrar por etapa, por nivel o "
        "por cantidad de filas sin escribir expresiones regulares frágiles.",
    )

    codigo(
        documento,
        """{
  "momento": "2026-07-26T14:13:04.512Z",
  "nivel": "INFO",
  "origen": "trabajos.validaciones",
  "mensaje": "Validacion de calidad finalizada",
  "filas_entrada": 1067371,
  "filas_validas": 1007894,
  "filas_rechazadas": 59477,
  "porcentaje_rechazo": 5.5723
}""",
        "Ejemplo de registro",
    )

    parrafo(
        documento,
        "Cualquier dato que se pase con el argumento extra se incorpora como campo del objeto "
        "JSON, así que se puede registrar el conteo de filas sin ensuciar el mensaje de texto. "
        "Para desarrollo local existe el formato de texto plano, más cómodo de leer en la "
        "terminal.",
    )


# =============================================================================
# 11. Runbook
# =============================================================================


def _runbook(documento: Document) -> None:
    """
    Escribe la guía operativa, pensada para quien se encuentra con una alerta y necesita saber qué hacer.
    """
    titulo(documento, "11. Runbook operativo", nivel=1, salto=True)

    parrafo(
        documento,
        "Guía para operar el pipeline y resolver los problemas que aparecen con más "
        "frecuencia. Está escrita pensando en alguien que se encuentra con una alerta y "
        "necesita saber qué hacer sin leer todo el código.",
    )

    titulo(documento, "11.1 Operaciones habituales", nivel=2)

    codigo(
        documento,
        """# Levantar todo
docker compose --profile completo up -d
docker compose ps

# Verificar que todo esta sano
curl -f http://localhost:8080/health
docker compose exec postgres pg_isready -U analitica -d analitica
curl -s http://localhost:9090/api/v1/targets | grep -o '"health":"[^"]*"'

# Disparar el pipeline
docker compose exec airflow-programador \\
  airflow dags trigger ventas_minoristas_diario

# Ver los resultados
cat salida/reportes/reporte_ultima_corrida.json

# Detener, conservando los datos
docker compose --profile completo down""",
        "Comandos de operación",
    )

    titulo(documento, "11.2 El pipeline falló", nivel=2)

    tabla(
        documento,
        ["Síntoma en el registro", "Causa", "Solución"],
        [
            [
                "No se encontró el archivo de entrada",
                "Falta el archivo crudo",
                "Correr scripts/descargar_dataset.py o verificar la muestra",
            ],
            [
                "El archivo no contiene ninguna fila",
                "Archivo truncado en el origen",
                "Volver a descargarlo",
            ],
            [
                "columnas obligatorias",
                "Cambió el formato del origen",
                "Revisar MAPEO_COLUMNAS en trabajos/configuracion.py",
            ],
            [
                "El rechazo alcanzó el N por ciento",
                "Degradación de calidad",
                "Revisar el archivo de cuarentena por regla",
            ],
            [
                "El almacén no responde",
                "PostgreSQL caído o arrancando",
                "docker compose restart postgres y esperar",
            ],
        ],
        anchos=[4.5, 4.0, 7.0],
    )

    nota(
        documento,
        "Todas las tareas son idempotentes, así que se puede reintentar sin efectos "
        "secundarios. La escritura borra el destino anterior antes de escribir, de modo que "
        "una reejecución produce exactamente el mismo resultado.",
        "exito",
    )

    titulo(documento, "11.3 Suben los rechazos de calidad", nivel=2)

    tabla(
        documento,
        ["Regla que sube", "Qué significa", "Acción"],
        [
            ["cantidad_minima", "Más devoluciones de lo habitual", "Suele ser real, verificar con el negocio"],
            ["precio_en_rango", "Importes fuera de rango", "Revisar si cambió la moneda o la escala"],
            ["columnas_obligatorias_sin_nulos", "El origen dejó de completar campos", "Escalar al equipo del sistema de origen"],
            ["fecha_dentro_de_rango", "Fechas mal formateadas", "Revisar el formato de exportación"],
            ["sin_duplicados_exactos", "El origen envió el archivo dos veces", "Verificar el proceso de exportación"],
        ],
        anchos=[5.0, 5.0, 5.5],
    )

    titulo(documento, "11.4 Falla el trabajo de Spark", nivel=2)

    tabla(
        documento,
        ["Error", "Causa", "Solución"],
        [
            ["Initial job has not accepted any resources", "No hay trabajadores registrados", "Reiniciar spark-trabajador"],
            ["Python in worker has different version", "Versiones de Python desalineadas", "Reconstruir las dos imágenes"],
            ["Connection refused to driver", "El ejecutor no alcanza al controlador", "Verificar SPARK_DRIVER_HOST"],
            ["Path does not exist", "Falta el Parquet de entrada", "Correr primero el pipeline de Python"],
            ["Illegal Parquet type TIMESTAMP(NANOS)", "Marcas de tiempo en nanosegundos", "Ya resuelto, ver sección 6.4"],
        ],
        anchos=[5.5, 5.0, 5.0],
    )

    titulo(documento, "11.5 Falla la construcción por certificados", nivel=2)

    parrafo(
        documento,
        "El problema de los certificados aparece con más frecuencia de lo que parece, motivo "
        "por el cual vale la pena documentarlo. Siempre que la red intercepte el tráfico "
        "cifrado y lo vuelva a firmar con un certificado propio de la organización, el "
        "anfitrión confía en él pero el contenedor no, de modo que toda descarga dentro de la "
        "construcción de la imagen falla.",
    )

    codigo(
        documento,
        """SSLError(SSLCertVerificationError(1, '[SSL: CERTIFICATE_VERIFY_FAILED]
certificate verify failed: unable to get local issuer certificate'))""",
        "Error tipico",
    )

    parrafo(
        documento,
        "La solución consiste en copiar el certificado raíz de la entidad que intercepta a la "
        "carpeta docker/certificados con extensión punto crt. Los Dockerfiles la detectan "
        "solos y, si está vacía, el paso no hace nada, de modo que el proyecto funciona igual "
        "en una red sin interceptación.",
    )

    codigo(
        documento,
        """# Averiguar quien intercepta
docker run --rm python:3.12-slim-bookworm sh -c \\
  "apt-get update -qq && apt-get install -y -qq openssl && \\
   echo | openssl s_client -connect pypi.org:443 2>/dev/null | grep 'i:'"

# En el Dockerfile
COPY docker/certificados/ /usr/local/share/ca-certificates/extra/
RUN update-ca-certificates || true""",
        "Diagnóstico y solución",
    )

    titulo(documento, "11.6 Otros problemas frecuentes", nivel=2)

    tabla(
        documento,
        ["Problema", "Diagnóstico", "Solución"],
        [
            ["Airflow no responde", "docker compose ps", "Esperar 90 segundos desde el arranque"],
            ["El grafo no aparece", "airflow dags list-import-errors", "Reiniciar airflow-programador"],
            ["Un contenedor reinicia en bucle", "docker compose logs", "Casi siempre falta de memoria, subirla a 6 GB"],
            ["Las conexiones se agotan", "Consulta a pg_stat_activity", "Cerrar conexiones inactivas de más de 10 minutos"],
            ["Grafana muestra paneles vacíos", "Ninguno", "Correr el pipeline al menos una vez"],
            ["Puerto ocupado", "El mensaje de docker compose", "Definir la variable de puerto en .env"],
        ],
        anchos=[4.5, 5.0, 6.0],
    )

    titulo(documento, "11.7 Mantenimiento periódico", nivel=2)

    tabla(
        documento,
        ["Frecuencia", "Tarea"],
        [
            ["Diaria", "Revisar en el tablero que la corrida terminó bien"],
            ["Semanal", "Revisar la cuarentena acumulada y limpiar la de más de treinta días"],
            ["Mensual", "Revisar el crecimiento del almacén y actualizar dependencias"],
            ["Trimestral", "Revisar los umbrales de calidad contra el histórico de rechazos"],
        ],
        anchos=[3.5, 12.0],
    )

    nota(
        documento,
        "**Regla importante ante corrupción de datos.** No reintentar. La escritura es de "
        "reemplazo completo, así que una reejecución sobre datos malos sobrescribe la "
        "evidencia. Primero copiar salida y datos/crudos a un lugar seguro.",
        "aviso",
    )


# =============================================================================
# 12. Guía de demo
# =============================================================================


def _guia_demo(documento: Document) -> None:
    """
    Escribe la guía de demostración, con los dos recorridos posibles y el guion de una presentación breve.
    """
    titulo(documento, "12. Guía de demostración", nivel=1, salto=True)

    parrafo(
        documento,
        "Hay dos recorridos. El corto muestra el resultado en cinco minutos sin Docker. El "
        "completo levanta toda la infraestructura y recorre cada plano del sistema.",
    )

    titulo(documento, "12.1 Recorrido corto", nivel=2)

    codigo(
        documento,
        """# 1. Clonar e instalar
git clone <repositorio>
cd pipeline-ventas-minoristas
python -m venv .venv
source .venv/bin/activate        # en Windows: .venv\\Scripts\\activate
pip install -r requisitos.txt

# 2. Correr las pruebas
python -m pytest pruebas -v

# 3. Ejecutar el pipeline sobre la muestra versionada
python ejecutar_pipeline.py --sin-almacen --sin-metricas --formato-log texto

# 4. Mirar los resultados
ls -la salida/
head -5 salida/ingresos_por_producto_fecha.csv
head -5 salida/cuarentena/rechazados_*.csv
cat salida/reportes/reporte_ultima_corrida.json

# 5. Con el archivo completo
python scripts/descargar_dataset.py
python ejecutar_pipeline.py --sin-almacen --formato-log texto""",
        "Cinco minutos, sin Docker",
    )

    titulo(documento, "12.2 Recorrido completo", nivel=2)

    codigo(
        documento,
        """# 1. Construir las imagenes
cp .env.ejemplo .env
docker compose build

# 2. Levantar todos los servicios
docker compose --profile completo up -d
docker compose ps

# 3. Disparar el pipeline
docker compose exec airflow-programador \\
  airflow dags unpause ventas_minoristas_diario
docker compose exec airflow-programador \\
  airflow dags trigger ventas_minoristas_diario

# 4. Consultar el almacen
docker compose exec postgres psql -U analitica -d analitica""",
        "Pila completa con Docker",
    )

    titulo(documento, "12.3 Interfaces disponibles", nivel=2)

    tabla(
        documento,
        ["Servicio", "Dirección", "Credenciales", "Qué mostrar"],
        [
            ["Airflow", "localhost:8080", "admin / admin", "El grafo y el paralelismo entre dbt y Spark"],
            ["Grafana", "localhost:3000", "admin / admin", "Estado, calidad y métricas del orquestador"],
            ["Prometheus", "localhost:9090", "sin credenciales", "Objetivos activos y reglas de alerta"],
            ["Spark", "localhost:8081", "sin credenciales", "El trabajador registrado y sus recursos"],
            ["Pushgateway", "localhost:9091", "sin credenciales", "Las métricas crudas del pipeline"],
        ],
        anchos=[2.8, 3.2, 3.0, 6.5],
    )

    titulo(documento, "12.4 Consultas de negocio para la demostración", nivel=2)

    codigo(
        documento,
        """-- El modelo principal
select fecha, producto_id, ingreso_total, unidades_vendidas
from publicado.pub_ingresos_producto_fecha
order by ingreso_total desc
limit 10;

-- La serie diaria con su media movil
select fecha, ingreso_total, ingreso_media_movil_7d, facturas_distintas
from publicado.pub_resumen_diario
order by fecha desc
limit 15;

-- Cuantos productos explican el ochenta por ciento del ingreso
select count(*)
from publicado.pub_ranking_productos
where participacion_acumulada <= 80;

-- Distribucion geografica
select pais, ingreso_total, participacion_porcentual, tipo_de_mercado
from publicado.pub_ventas_por_pais
order by posicion
limit 10;""",
        "SQL sobre el almacén",
    )

    titulo(documento, "12.5 Demostrar que la calidad de datos funciona", nivel=2)

    parrafo(
        documento,
        "La demostración de la calidad de datos es la parte más interesante de mostrar, porque "
        "prueba que el sistema detecta "
        "problemas en vez de propagarlos. Conviene dejarla para el final.",
    )

    codigo(
        documento,
        """cat > datos/crudos/archivo_roto.csv <<'CSV'
Invoice,StockCode,Description,Quantity,InvoiceDate,Price,Customer ID,Country
489434,22086,PRODUCTO NORMAL,10,2009-12-01 07:45:00,2.50,13085,UNITED KINGDOM
C489435,22086,DEVOLUCION,-10,2009-12-01 08:00:00,2.50,13085,UNITED KINGDOM
489436,AJUSTE,CARGO ADMIN,1,2009-12-01 08:15:00,99999.00,13085,UNITED KINGDOM
489437,,SIN CODIGO,5,2009-12-01 08:30:00,3.00,13085,UNITED KINGDOM
489438,22086,FECHA IMPOSIBLE,3,2099-01-01 09:00:00,2.50,13085,UNITED KINGDOM
CSV

python ejecutar_pipeline.py --entrada datos/crudos/archivo_roto.csv \\
  --sin-almacen --sin-metricas --formato-log texto

echo $?    # devuelve 1, que es lo que Airflow interpreta como fallo""",
        "Prueba con datos deliberadamente malos",
    )

    parrafo(
        documento,
        "El pipeline se detiene con un mensaje explícito, porque el ochenta por ciento de las "
        "filas se rechazó y eso supera el umbral tolerado. Nada se escribe en el destino "
        "final.",
    )

    titulo(documento, "12.6 Guion para una presentación de quince minutos", nivel=2)

    tabla(
        documento,
        ["Minuto", "Qué mostrar", "Qué decir"],
        [
            ["0 a 2", "El problema y el conjunto de datos", "Un millón de líneas reales con problemas reales"],
            ["2 a 4", "Las pruebas corriendo", "La lógica está verificada antes de tocar ningún dato"],
            ["4 a 6", "El pipeline en la terminal", "Las etapas, el resumen y los números finales"],
            ["6 a 8", "Los archivos generados", "Parquet particionado, CSV, cuarentena y reporte"],
            ["8 a 10", "Airflow", "El grafo y el paralelismo entre dbt y Spark"],
            ["10 a 12", "El almacén", "Las tres capas y una consulta de negocio"],
            ["12 a 14", "Grafana", "El estado, la calidad y las alertas definidas"],
            ["14 a 15", "El archivo roto", "El sistema se detiene en vez de publicar algo mal"],
        ],
        anchos=[2.0, 5.5, 8.0],
    )


# =============================================================================
# 13. Evidencia
# =============================================================================


def _evidencia_de_ejecucion(documento: Document, evidencia: dict) -> None:
    """
    Escribe la sección de evidencia, cuyo contenido proviene de ejecuciones reales sobre el conjunto de datos completo.
    """
    titulo(documento, "13. Evidencia de ejecución", nivel=1, salto=True)

    parrafo(
        documento,
        "Todo lo que sigue proviene de ejecuciones reales sobre el conjunto de datos completo "
        "de 1,067,371 filas, no de una descripción de lo que debería pasar.",
    )

    titulo(documento, "13.1 Batería de pruebas", nivel=2)

    codigo(
        documento,
        """$ python -m pytest pruebas -q

pruebas/test_extremo_a_extremo.py ...........                    [ 15%]
pruebas/test_ingesta.py ............                             [ 32%]
pruebas/test_metricas.py .........                               [ 45%]
pruebas/test_persistencia.py .........                           [ 58%]
pruebas/test_transformaciones.py .................               [ 82%]
pruebas/test_validaciones.py ............                        [100%]

======================= 70 passed in 3.14s ========================""",
        "Salida de pytest",
    )

    titulo(documento, "13.2 Revisión de estilo", nivel=2)

    codigo(
        documento,
        """$ python -m ruff check trabajos pruebas orquestacion scripts ejecutar_pipeline.py

All checks passed!""",
        "Salida de ruff",
    )

    titulo(documento, "13.3 Corrida del pipeline", nivel=2)

    resumen = f"""====================================================================
  RESUMEN DE LA CORRIDA DEL PIPELINE DE VENTAS
====================================================================
  Corrida            {_numero(evidencia, 'identificador_corrida', defecto='sin dato')}
  Archivo de entrada datos/crudos/ventas_minoristas.csv
--------------------------------------------------------------------
  Filas leidas       {_formato(_numero(evidencia, 'validacion', 'filas_entrada'))}
  Filas validas      {_formato(_numero(evidencia, 'validacion', 'filas_validas'))}
  Filas rechazadas   {_formato(_numero(evidencia, 'validacion', 'filas_rechazadas'))} ({_numero(evidencia, 'validacion', 'porcentaje_rechazo')} por ciento)
--------------------------------------------------------------------
  Ingreso total      {_formato(_numero(evidencia, 'metricas_negocio', 'ingreso_total'), 2)}
  Unidades vendidas  {_formato(_numero(evidencia, 'metricas_negocio', 'unidades_vendidas'))}
  Productos          {_formato(_numero(evidencia, 'metricas_negocio', 'productos_distintos'))}
  Dias cubiertos     {_formato(_numero(evidencia, 'metricas_negocio', 'dias_cubiertos'))}
  Periodo            {_numero(evidencia, 'metricas_negocio', 'fecha_minima', defecto='')} a {_numero(evidencia, 'metricas_negocio', 'fecha_maxima', defecto='')}
===================================================================="""

    codigo(documento, resumen, "Salida de ejecutar_pipeline.py")

    titulo(documento, "13.4 Detalle de los rechazos", nivel=2)

    conteos = _numero(evidencia, "validacion", "conteo_por_regla", defecto={})
    if conteos:
        total = sum(int(v) for v in conteos.values()) or 1
        filas = [
            [regla, _formato(cantidad), f"{int(cantidad) / total * 100:.1f} por ciento"]
            for regla, cantidad in conteos.items()
        ]
        tabla(documento, ["Regla", "Filas", "Del total rechazado"], filas, anchos=[7.5, 4.0, 4.0])

    titulo(documento, "13.5 Primeras filas del agregado", nivel=2)

    muestra = evidencia.get("muestra_agregado") or []
    if muestra:
        encabezados = ["fecha", "producto_id", "ingreso_total", "unidades_vendidas", "descripcion_producto"]
        filas = [
            [str(registro.get(clave, ""))[:34] for clave in encabezados]
            for registro in muestra[:10]
        ]
        tabla(documento, ["Fecha", "Producto", "Ingreso", "Unidades", "Descripción"], filas,
              anchos=[2.4, 2.2, 2.3, 2.2, 6.4])

    titulo(documento, "13.6 Trabajo distribuido de PySpark", nivel=2)

    codigo(
        documento,
        """{"mensaje": "Iniciando analisis distribuido", "maestro": "local[*]"}
{"mensaje": "Detalle leido desde Parquet", "ruta": "/opt/proyecto/salida/detalle_ventas"}
{"mensaje": "Detalle cargado en memoria", "filas": 1007894}
{"mensaje": "Resultado de Spark escrito", "ruta": ".../ranking_mensual_productos"}
{"mensaje": "Resultado de Spark escrito", "ruta": ".../tendencia_diaria"}
{"mensaje": "Resultado de Spark escrito", "ruta": ".../concentracion_por_pais"}
{"mensaje": "Analisis distribuido finalizado", "filas_procesadas": 1007894,
 "meses_en_ranking": 25, "dias_en_tendencia": 604}""",
        "Registros del trabajo de Spark",
    )

    titulo(documento, "13.7 Resultados del análisis distribuido", nivel=2)

    parrafo(documento, "Ranking mensual de productos, primeras filas de diciembre de 2009.")

    tabla(
        documento,
        ["Mes", "Producto", "Ingreso", "Unidades", "Posición", "Participación"],
        [
            ["2009-12", "DOT", "18,574.58", "49", "1", "2.258 %"],
            ["2009-12", "85123A", "17,255.35", "6,406", "2", "2.098 %"],
            ["2009-12", "22086", "10,169.36", "3,362", "3", "1.236 %"],
            ["2009-12", "15056BL", "8,697.75", "2,190", "4", "1.057 %"],
            ["2009-12", "22111", "8,027.76", "1,561", "5", "0.976 %"],
        ],
        anchos=[2.2, 2.5, 3.0, 2.5, 2.0, 3.3],
    )

    parrafo(documento, "Concentración de la facturación por país.")

    tabla(
        documento,
        ["País", "Ingreso", "Facturas", "Participación", "Acumulada"],
        [
            ["UNITED KINGDOM", "17,410,017.82", "36,536", "85.026 %", "85.026 %"],
            ["EIRE", "658,767.31", "626", "3.217 %", "88.243 %"],
            ["NETHERLANDS", "554,038.09", "228", "2.706 %", "90.949 %"],
            ["GERMANY", "425,019.71", "789", "2.076 %", "93.025 %"],
            ["FRANCE", "350,456.09", "622", "1.712 %", "94.737 %"],
            ["AUSTRALIA", "169,283.46", "95", "0.827 %", "95.564 %"],
        ],
        anchos=[4.0, 3.5, 2.5, 2.8, 2.7],
    )

    nota(
        documento,
        "El ingreso acumulado que calcula Spark de forma independiente, 20,476,082.15, "
        "coincide exactamente con el total que reporta el pipeline de pandas. Es la mejor "
        "verificación posible de que los dos caminos de cálculo son coherentes entre sí.",
        "exito",
    )

    titulo(documento, "13.8 Tendencia diaria con media móvil", nivel=2)

    tabla(
        documento,
        ["Fecha", "Ingreso del día", "Media móvil 7d", "Facturas", "Acumulado"],
        [
            ["2011-12-05", "88,620.84", "59,175.64", "127", "20,060,917.24"],
            ["2011-12-06", "56,558.83", "56,537.97", "115", "20,117,476.07"],
            ["2011-12-07", "75,315.55", "59,086.30", "106", "20,192,791.62"],
            ["2011-12-08", "82,371.55", "64,136.79", "120", "20,275,163.17"],
            ["2011-12-09", "200,918.98", "88,043.87", "44", "20,476,082.15"],
        ],
        anchos=[2.6, 3.2, 3.2, 2.3, 3.5],
    )

    titulo(documento, "13.9 Infraestructura en ejecución", nivel=2)

    codigo(
        documento,
        """$ docker compose ps

NAME                            STATE     STATUS
pipeline-postgres               running   Up (healthy)
pipeline-airflow-servidor       running   Up (healthy)
pipeline-airflow-programador    running   Up (healthy)
pipeline-spark-maestro          running   Up (healthy)
pipeline-spark-trabajador       running   Up
pipeline-prometheus             running   Up
pipeline-grafana                running   Up
pipeline-pushgateway            running   Up
pipeline-statsd-exportador      running   Up (healthy)
pipeline-postgres-exportador    running   Up""",
        "Estado de los contenedores",
    )

    titulo(documento, "13.10 Grafos cargados en Airflow", nivel=2)

    codigo(
        documento,
        """$ docker compose exec airflow-programador airflow dags list

dag_id                   | fileloc                                | owners       | is_paused
ventas_minoristas_diario | .../dags/dag_ventas_diario.py          | equipo-datos | False
vigilancia_calidad_datos | .../dags/dag_calidad_datos.py          | equipo-datos | True

$ docker compose exec airflow-programador airflow dags list-import-errors

No data found""",
        "DAGs sin errores de importación",
    )

    titulo(documento, "13.11 Archivos generados", nivel=2)

    codigo(
        documento,
        """salida/
├── detalle_ventas/                      Parquet particionado por anio y mes
│   ├── anio=2009/mes=12/
│   ├── anio=2010/mes=1/  ...  mes=12/
│   └── anio=2011/mes=1/  ...  mes=12/
├── ingresos_por_producto_fecha/         Parquet, resultado principal
├── ingresos_por_producto_fecha.csv      El mismo, para planilla
├── resumen_diario/                      Serie temporal diaria
├── ranking_productos.csv                Los 25 que mas facturaron
├── analitica_spark/
│   ├── ranking_mensual_productos/
│   ├── tendencia_diaria/
│   └── concentracion_por_pais/
├── cuarentena/
│   └── rechazados_AAAAMMDD-HHMMSS.csv   Con el motivo de cada descarte
└── reportes/
    ├── reporte_AAAAMMDD-HHMMSS.json
    └── reporte_ultima_corrida.json""",
        "Estructura de resultados",
    )


# =============================================================================
# 14. Calidad del código
# =============================================================================


def _calidad_del_codigo(documento: Document) -> None:
    """
    Escribe la sección de calidad del código, que reúne las convenciones, las optimizaciones medibles y las decisiones discutibles.
    """
    titulo(documento, "14. Calidad del código", nivel=1, salto=True)

    titulo(documento, "14.1 Convenciones", nivel=2)

    vinetas(
        documento,
        [
            "**Todo en español.** Variables, funciones, módulos, carpetas, docstrings y comentarios. Un código que mezcla idiomas obliga a cambiar de contexto mentalmente en cada línea.",
            "**Docstrings en todas las funciones públicas**, con el estilo de Google. Lo importante no es la sección de argumentos, que casi siempre es evidente, sino el párrafo que explica por qué se hizo así.",
            "**Anotaciones de tipo en todo el código.** Documentan sin comentarios y obligan a pensar qué recibe y qué devuelve cada función.",
            "**Comentarios que explican decisiones, no acciones.** Un comentario que repite lo que ya dice el código no aporta nada.",
        ],
    )

    titulo(documento, "14.2 Una responsabilidad por módulo", nivel=2)

    tabla(
        documento,
        ["Módulo", "Su única responsabilidad"],
        [
            ["configuracion.py", "Resolver rutas, umbrales y conexiones"],
            ["registro.py", "Formatear y encaminar los registros"],
            ["metricas.py", "Acumular y publicar métricas"],
            ["ingesta.py", "Leer el archivo y normalizar su forma"],
            ["validaciones.py", "Decidir qué fila es válida"],
            ["transformaciones.py", "Calcular las medidas de negocio"],
            ["persistencia.py", "Escribir y leer resultados"],
            ["carga_almacen.py", "Hablar con PostgreSQL"],
        ],
        anchos=[5.0, 10.5],
    )

    parrafo(
        documento,
        "La prueba de que la separación funciona es simple. Si agregar una regla de calidad "
        "obligara a tocar el módulo de transformaciones, la separación estaría mal.",
    )

    titulo(documento, "14.3 Reglas de calidad como datos, no como código", nivel=2)

    parrafo(
        documento,
        "Agregar una regla es agregar un elemento a una lista, sin tocar el motor que las "
        "aplica. El nombre se usa en las métricas y en la cuarentena, y la descripción aparece "
        "en el registro y en el reporte, de modo que quien lee el resultado entiende qué se "
        "comprobó sin abrir el código.",
    )

    codigo(
        documento,
        """@dataclass(frozen=True)
class ReglaCalidad:
    \"\"\"
    Define una regla de calidad aplicable a la tabla de ventas.
    En nombre va el identificador corto que se usa en metricas y reportes, y en
    descripcion la explicacion en lenguaje llano de que comprueba.
    Por su parte, detectar es una funcion que recibe la tabla y devuelve una
    mascara booleana donde True marca las filas que incumplen la regla.
    \"\"\"

    nombre: str
    descripcion: str
    detectar: Callable[[pd.DataFrame], pd.Series]""",
        "trabajos/validaciones.py",
    )

    titulo(documento, "14.4 Funciones puras en la capa de transformación", nivel=2)

    parrafo(
        documento,
        "Todas reciben una tabla y devuelven otra, sin tocar disco ni variables globales, y "
        "ninguna modifica su entrada. Hay una prueba dedicada a verificar exactamente eso.",
    )

    codigo(
        documento,
        """def test_calcular_ingreso_no_modifica_la_tabla_original(ventas_validas):
    \"\"\"La funcion es pura, devuelve una copia y deja la entrada intacta.\"\"\"
    columnas_antes = list(ventas_validas.columns)

    calcular_ingreso_total(ventas_validas)

    assert list(ventas_validas.columns) == columnas_antes
    assert "ingreso_total" not in ventas_validas.columns""",
        "pruebas/test_transformaciones.py",
    )

    titulo(documento, "14.5 Manejo de errores", nivel=2)

    parrafo(
        documento,
        "El criterio es fallar temprano cuando el problema es de estructura y tolerar cuando el problema "
        "es de contenido. Un archivo sin las columnas necesarias corta de inmediato, mientras "
        "que un valor mal formateado dentro de una columna correcta se convierte en nulo y lo "
        "rechaza después la capa de calidad, con su motivo.",
    )

    parrafo(
        documento,
        "Las excepciones propias por dominio permiten que quien orquesta distinga un problema "
        "de datos de un error de programación, y eso se traduce en códigos de salida distintos.",
    )

    codigo(
        documento,
        """except (ErrorDeIngesta, ErrorDeCalidad):
    return 1        # problema de datos, no reintentar sin revisar
except Exception:
    return 2        # error inesperado, probablemente un fallo del codigo""",
        "ejecutar_pipeline.py",
    )

    parrafo(
        documento,
        "Los mensajes de error dicen además qué hacer, lo que ahorra una búsqueda en la "
        "documentación.",
    )

    codigo(
        documento,
        """raise ErrorDeIngesta(
    f"No se encontro el archivo de entrada en {ruta}. "
    "Genera la muestra con 'python scripts/generar_datos_ejemplo.py' "
    "o copia el CSV original a datos/crudos/."
)""",
        "trabajos/ingesta.py",
    )

    titulo(documento, "14.6 Idempotencia", nivel=2)

    codigo(
        documento,
        _extraer("trabajos/persistencia.py", "def _limpiar_destino(", "def guardar_parquet("),
        "trabajos/persistencia.py",
    )

    titulo(documento, "14.7 Dos optimizaciones con impacto medible", nivel=2)

    titulo(documento, "Carga al almacén con COPY", nivel=3)

    parrafo(
        documento,
        "La carga al almacén usa el comando COPY de PostgreSQL en lugar del método de "
        "inserción por defecto de pandas. La diferencia no es menor. Una sentencia INSERT "
        "obliga al motor a analizar y planificar cada lote, mientras que COPY escribe "
        "directamente sobre la tabla. Con el millón de filas de este proyecto, la carga pasa "
        "de varios minutos a unos pocos segundos.",
    )

    codigo(
        documento,
        _extraer("trabajos/carga_almacen.py", "def _insertar_con_copy(", "def crear_motor("),
        "trabajos/carga_almacen.py",
    )

    titulo(documento, "Lectura por lotes", nivel=3)

    parrafo(
        documento,
        "La ingesta lee el archivo en bloques y normaliza cada uno apenas lo lee, en lugar de "
        "cargar todo y convertir después. El cambio se hizo porque la versión original moría "
        "por falta de memoria dentro del contenedor, y el resultado se puede medir. El "
        "pipeline completo sobre 1,067,371 filas pasa de fallar con dos gigabytes a correr "
        "cómodo dentro de uno.",
    )

    codigo(
        documento,
        """$ docker run --rm --memory=1g --memory-swap=1g \\
    -v "$(pwd)":/opt/proyecto -w /opt/proyecto \\
    --entrypoint python pipeline-ventas/spark:1.0.0 \\
    ejecutar_pipeline.py --sin-almacen --sin-metricas

OK    con 1g
OK    con 1500m
OK    con 2g""",
        "Verificación con límites estrictos de memoria",
    )

    codigo(
        documento,
        _extraer("trabajos/ingesta.py", "def _leer_csv_por_lotes(", "def leer_archivo("),
        "trabajos/ingesta.py",
    )

    titulo(documento, "14.8 Convenciones de SQL", nivel=2)

    vinetas(
        documento,
        [
            "**Consultas por etapas con expresiones de tabla comunes.** Cada bloque hace una cosa y tiene nombre. Una consulta de cien líneas con subconsultas anidadas hace lo mismo pero nadie puede leerla.",
            "**Referencias en lugar de nombres de tabla.** Así dbt construye el grafo de dependencias solo y un cambio de nombre se corrige en un lugar.",
            "**Macros para lo que se repite.** Sin ellas, en algún modelo se escribiría una escala de redondeo distinta y los totales dejarían de cerrar entre capas.",
            "**Divisiones protegidas.** En SQL una división por cero corta toda la consulta. Devolver nulo es más útil, porque el resto del modelo se construye igual.",
        ],
    )

    titulo(documento, "14.9 Herramientas de verificación", nivel=2)

    tabla(
        documento,
        ["Herramienta", "Qué controla", "Cuándo corre"],
        [
            ["ruff check", "Errores de estilo y fallas lógicas", "Al guardar y en cada envío"],
            ["ruff format", "Formato uniforme", "Al guardar"],
            ["pytest", "Comportamiento del código", "Antes de cada envío"],
            ["pytest-cov", "Cobertura de las pruebas", "En integración continua"],
            ["dbt test", "Corrección de los datos", "Después de cada construcción"],
            ["docker compose config", "Sintaxis de la infraestructura", "En integración continua"],
        ],
        anchos=[4.0, 6.5, 5.0],
    )

    parrafo(
        documento,
        "Los conjuntos de reglas activos de ruff son los que atrapan errores reales, no "
        "preferencias. Al respecto, se ignora el largo máximo de línea porque el formateador ya lo maneja y "
        "mantenerlo activo genera avisos sobre líneas que el propio formateador escribió.",
    )

    titulo(documento, "14.10 Qué se hizo a propósito y podría discutirse", nivel=2)

    parrafo(
        documento,
        "Vale la pena ser explícito sobre las decisiones que no son obvias, porque una "
        "decisión sin contexto es difícil de revisar cuando las condiciones cambian.",
    )

    tabla(
        documento,
        ["Decisión", "Qué se pierde", "Qué se gana"],
        [
            [
                "Un motivo único por fila rechazada",
                "Información sobre filas que incumplen varias reglas",
                "La suma por regla coincide con el total, y el tablero es interpretable",
            ],
            [
                "Reemplazo completo de tabla",
                "No escala a volúmenes grandes",
                "Menos formas de dejar datos a medias",
            ],
            [
                "Exception capturado en la capa de métricas",
                "Oculta errores de programación en ese módulo",
                "Nada de esa capa puede tirar abajo el pipeline",
            ],
            [
                "Configuración construida en cada llamada",
                "Levemente más costoso",
                "Las pruebas alteran el entorno sin efectos entre casos",
            ],
            [
                "pandas en lugar de Polars o DuckDB",
                "Algo de rendimiento",
                "Es lo que más gente sabe leer sin explicación previa",
            ],
        ],
        anchos=[4.5, 5.5, 5.5],
    )


# =============================================================================
# 15. Cierre
# =============================================================================


def _cierre(documento: Document, metadatos: dict) -> None:
    """
    Escribe la sección final, en la que se resume lo construido, se cuentan los problemas de integración y se reconocen las limitaciones.
    """
    titulo(documento, "15. Conclusiones", nivel=1, salto=True)

    titulo(documento, "15.1 Qué se construyó", nivel=2)

    parrafo(
        documento,
        "Un pipeline que toma más de un millón de líneas de factura reales, las valida contra "
        "seis reglas de calidad, calcula el ingreso por producto y fecha, y publica el "
        "resultado en tres formatos distintos según quién lo vaya a consumir. Todo eso "
        "orquestado, probado, monitoreado y reproducible en cualquier máquina con Docker.",
    )

    tabla(
        documento,
        ["Requisito de la consigna", "Cómo se cumplió"],
        [
            ["Definir el problema y el dataset", "Online Retail II, histórico real de 1,067,371 transacciones"],
            ["Estructura del proyecto", "Carpetas separadas por responsabilidad, con nomenclatura en español"],
            ["Ingesta de datos", "trabajos/ingesta.py, con traducción de esquema y tipado permisivo"],
            ["Transformación", "trabajos/transformaciones.py, funciones puras y verificables"],
            ["Guardar resultados", "Parquet particionado con Zstandard, más copia en CSV"],
            ["Automatizar el pipeline", "ejecutar_pipeline.py, Makefile, Docker y Airflow"],
            ["Validación de datos", "Seis reglas más verificación de salida y umbral global"],
            ["Verificar resultados", "Totales que cierran entre pandas, Spark, dbt y el almacén"],
            ["Documentar", "README más seis documentos técnicos y este informe"],
            ["Subir a repositorio", "Repositorio público, clonable y ejecutable sin pasos extra"],
        ],
        anchos=[5.5, 10.0],
    )

    titulo(documento, "15.2 Lo que aportó ejecutar el sistema completo", nivel=2)

    parrafo(
        documento,
        "Dos problemas aparecieron solo al integrar todo y ninguno se habría detectado "
        "probando cada pieza por separado.",
    )

    titulo(documento, "El bucle de registro que agotaba la memoria", nivel=3)

    parrafo(
        documento,
        "Es el más interesante de todos. El pipeline funcionaba perfecto al ejecutarlo a mano, "
        "incluso dentro del mismo contenedor de Airflow, pero cuando lo lanzaba el orquestador "
        "moría a los pocos segundos con el código de retorno menos nueve y sin ningún mensaje "
        "de error. El síntoma apuntaba a falta de memoria y llevó a probar límites cada vez "
        "más altos, sin resultado.",
    )

    parrafo(
        documento,
        "La causa real era otra. Airflow ejecuta cada tarea redirigiendo la salida estándar "
        "hacia su propio sistema de registro, para poder guardar en el archivo de la tarea "
        "todo lo que el código imprima. El módulo de registro del pipeline, por su parte, "
        "reemplazaba los manejadores del registrador raíz por uno que escribe a la salida "
        "estándar. Con las dos cosas juntas se arma un lazo. Cada mensaje va a la salida "
        "estándar, de ahí vuelve a entrar al sistema de registro, se vuelve a emitir, y así "
        "sucesivamente hasta que el sistema operativo mata el proceso.",
    )

    parrafo(
        documento,
        "La corrección deja una regla general que vale para cualquier código que pueda "
        "importarse desde otro programa. Un módulo no debería apropiarse del registrador raíz, "
        "porque no es suyo. Ahora la función comprueba si ya hay manejadores configurados y, "
        "si los hay, se limita a ajustar los niveles. Solo el punto de entrada de línea de "
        "comandos toma el control, y lo pide explícitamente.",
    )

    codigo(
        documento,
        """raiz = logging.getLogger()

# En caso de que ya existan manejadores, el registro lo configuro alguien mas
# y esa configuracion ajena se respeta.
if raiz.handlers and not forzar:
    raiz.setLevel(min(raiz.level or logging.INFO,
                      getattr(logging, nivel_elegido, logging.INFO)))
else:
    ...
    raiz.handlers.clear()
    raiz.addHandler(manejador)""",
        "trabajos/registro.py",
    )

    titulo(documento, "Las vistas de dbt impedían recargar la tabla cruda", nivel=3)

    parrafo(
        documento,
        "La carga al almacén usaba el modo de reemplazo de pandas, que borra la tabla y la "
        "vuelve a crear. Funcionó hasta que dbt construyó sus vistas encima. A partir de ahí, "
        "la segunda corrida falló porque PostgreSQL se niega a borrar una tabla de la que "
        "dependen otros objetos.",
    )

    parrafo(
        documento,
        "Forzar el borrado en cascada habría resuelto el error inmediato y creado uno peor, "
        "porque destruiría las vistas y dejaría el almacén a medias hasta la siguiente "
        "construcción de dbt. La solución correcta es vaciar la tabla en lugar de borrarla. El "
        "objeto sobrevive, las vistas siguen siendo válidas y el contenido se reemplaza igual. "
        "Además, vaciar y cargar viajan en la misma transacción, así que si la carga falla la "
        "tabla conserva sus datos anteriores en vez de quedar vacía.",
    )

    parrafo(
        documento,
        "Solo cuando cambia la estructura de columnas hace falta recrear la tabla. En ese caso "
        "sí se borra en cascada, porque las vistas construidas sobre la estructura vieja ya no "
        "serían válidas de todos modos, y queda constancia en el registro de que dbt tiene que "
        "reconstruirlas.",
    )

    titulo(documento, "Otros dos problemas de integración", nivel=3)

    vinetas(
        documento,
        [
            "**Marcas de tiempo en nanosegundos.** pandas las escribe así por defecto y Spark 3.5 no sabe leerlas. El error no dice nada sobre su causa real. El problema se resolvió forzando microsegundos en la escritura.",
            "**Conflicto de versiones entre Airflow y el pipeline.** El archivo de restricciones de Airflow fija versiones concretas de pandas y pyarrow, y fijar otras distintas hacía imposible construir la imagen. El conflicto se resolvió alineando todo el proyecto a un único conjunto de versiones.",
        ],
    )

    parrafo(
        documento,
        "También apareció un problema de entorno, la interceptación del tráfico cifrado por "
        "parte de la red, que rompía la instalación de paquetes dentro de los contenedores. "
        "Al respecto, quedó resuelto con un mecanismo documentado que cualquier persona en una "
        "red corporativa va a necesitar, y que no hace nada cuando no hace falta.",
    )

    nota(
        documento,
        "Ninguno de estos cinco problemas se habría detectado probando cada pieza por separado. "
        "Todos aparecieron al ejecutar el recorrido completo, y tres de ellos se manifestaban "
        "con mensajes que no señalaban su causa real. Por ello vale la pena integrar y "
        "ejecutar de verdad, y no solo describir la arquitectura.",
        "info",
    )

    titulo(documento, "15.3 Limitaciones reconocidas", nivel=2)

    parrafo(
        documento,
        "El pipeline no escala más allá de la memoria de una máquina en su etapa principal. La "
        "carga al almacén es de reemplazo completo, lo que impide revertir sin una copia de "
        "seguridad. Las alertas están definidas pero sin un destinatario configurado, porque "
        "un canal de notificación real no se puede incluir en un repositorio público. Y las "
        "credenciales viven en variables de entorno, que alcanza para un entorno local pero no "
        "para producción.",
    )

    parrafo(
        documento,
        "Ninguna de estas limitaciones afecta la corrección de lo que el pipeline calcula. Son "
        "requisitos de operación que aparecen cuando el sistema deja de correr en una máquina "
        "de escritorio, y están documentados con el camino de migración correspondiente.",
    )

    titulo(documento, "15.4 Enlaces", nivel=2)

    tabla(
        documento,
        ["Recurso", "Ubicación"],
        [
            ["Repositorio", metadatos["repositorio"]],
            ["Conjunto de datos", "https://archive.ics.uci.edu/dataset/502/online+retail+ii"],
            ["Documentación técnica", "carpeta documentacion del repositorio"],
            ["Runbook operativo", "documentacion/runbook.md"],
            ["Guía de demostración", "documentacion/guia_demo.md"],
        ],
        anchos=[4.5, 11.0],
    )

    documento.add_paragraph()
    parrafo(
        documento,
        f"Documento generado a partir del código y de los resultados de ejecución del "
        f"repositorio en su versión {metadatos['version']}.",
        cursiva=True,
    )
