"""
Grafo principal que orquesta el pipeline de ventas de punta a punta.
El orden de las tareas responde a las dependencias reales entre etapas y no a una preferencia estética.
Es decir, primero se verifica que estén dadas las condiciones para trabajar, después se procesa, luego se modela sobre lo procesado y al final se analiza el resultado.
Dicho de otro modo, cada bloque produce algo que el siguiente necesita.
Conviene precisar tres decisiones que no se deducen leyendo el archivo.
En primer lugar, el pipeline de Python se invoca como una función importada y no como un subproceso, de manera que una excepción llegue a Airflow con su rastro completo en lugar de un código de salida sin contexto.
A continuación, dbt se ejecuta con BashOperator porque vive en su propio entorno virtual, con versiones de bibliotecas incompatibles con las de Airflow, motivo por el cual llamarlo por su ruta absoluta mantiene los dos mundos separados.
Por último, las tareas de verificación inicial usan reintentos cortos porque su fallo típico es un servicio que todavía está arrancando, mientras que las de procesamiento los usan más espaciados porque el suyo es la contención de recursos, que necesita más tiempo para resolverse sola.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from airflow.decorators import task
from airflow.exceptions import AirflowFailException, AirflowSkipException
from airflow.models.dag import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.empty import EmptyOperator
from airflow.utils.task_group import TaskGroup
from airflow.utils.trigger_rule import TriggerRule

# El proyecto se monta en esta ruta dentro del contenedor, aunque la variable de entorno permite apuntarla al repositorio cuando el grafo se carga fuera de Docker.
RAIZ_PROYECTO = Path(os.environ.get("RAIZ_PROYECTO", "/opt/proyecto"))
if str(RAIZ_PROYECTO) not in sys.path:
    sys.path.insert(0, str(RAIZ_PROYECTO))

RUTA_DBT = RAIZ_PROYECTO / "dbt"
EJECUTABLE_DBT = "/opt/dbt_entorno/bin/dbt"

# Los argumentos siguientes los heredan todas las tareas del grafo, de modo que cada tarea solo declara aquello en lo que se aparta del criterio general.
ARGUMENTOS_POR_DEFECTO = {
    "owner": "equipo-datos",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=2),
    "retry_exponential_backoff": True,
    "max_retry_delay": timedelta(minutes=15),
    # Un tope por tarea evita que una consulta trabada deje el grafo colgado ocupando una ranura del ejecutor de forma indefinida.
    "execution_timeout": timedelta(minutes=45),
}

DOCUMENTACION = """
### Pipeline diario de ventas minoristas

El grafo procesa el histórico de transacciones y publica los agregados que consumen los tableros de negocio.
La corrida arranca todos los días a las seis de la mañana en horario universal y admite una sola ejecución activa a la vez.

**Etapas**

1. `preparacion` verifica que exista el archivo de entrada y que el almacén responda, todo ello antes de gastar tiempo de cómputo.
2. `procesar_ventas` corre la ingesta, la validación de calidad, las transformaciones y la escritura en Parquet y en PostgreSQL.
3. `modelado_dbt` construye las capas de preparación, intermedia y publicada, y a continuación corre las pruebas de datos sobre el resultado.
4. `analisis_distribuido` lanza el trabajo de PySpark contra el clúster, en paralelo con el modelado porque ninguno de los dos depende del otro.
5. `resumen_de_la_corrida` deja en el registro los números finales, de modo que revisar una corrida no obligue a abrir una consola de base de datos.

**Si algo falla**

Conviene consultar `documentacion/runbook.md`, donde está el procedimiento para cada fallo conocido.
Cabe señalar que todas las tareas son idempotentes, motivo por el cual se pueden reintentar sin efectos secundarios.
"""


with DAG(
    dag_id="ventas_minoristas_diario",
    description="Pipeline extremo a extremo de ventas minoristas",
    doc_md=DOCUMENTACION,
    default_args=ARGUMENTOS_POR_DEFECTO,
    start_date=datetime(2024, 1, 1),
    # La corrida se programa a las seis de la mañana en horario universal, hora en la que el archivo del día anterior ya está disponible y la máquina está libre.
    schedule="0 6 * * *",
    # No se recuperan las corridas pasadas, puesto que el proyecto procesa el histórico completo cada vez y ejecutar los días atrasados solo repetiría el mismo trabajo.
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(hours=2),
    tags=["ventas", "produccion", "diario"],
) as grafo:

    inicio = EmptyOperator(task_id="inicio")

    # -------------------------------------------------------------------------
    # En primer lugar se comprueba que estén dadas las condiciones para procesar.
    # -------------------------------------------------------------------------

    with TaskGroup(
        group_id="preparacion",
        tooltip="Comprueba que estén dadas las condiciones para procesar",
    ) as preparacion:

        @task(task_id="verificar_archivo_de_entrada", retries=3, retry_delay=timedelta(seconds=30))
        def verificar_archivo_de_entrada() -> dict[str, object]:
            """
            Confirma que hay un archivo para procesar y deja constancia de su tamaño.
            Al respecto, fallar en este punto cuesta segundos, mientras que fallar después de veinte minutos de procesamiento cuesta bastante más, motivo por el cual la comprobación va primero.
            Devuelve un diccionario con la ruta elegida y su tamaño en megabytes, que las tareas siguientes reciben por XCom.
            Lanza AirflowFailException en caso de que no haya ningún archivo disponible o de que el encontrado esté vacío.
            """
            from trabajos.configuracion import obtener_configuracion

            configuracion = obtener_configuracion()
            ruta = configuracion.resolver_entrada()

            if not ruta.exists():
                raise AirflowFailException(
                    f"No hay archivo de entrada. La búsqueda se hizo en {configuracion.ruta_entrada} "
                    f"y en {configuracion.ruta_muestra}."
                )

            tamanio_mb = round(ruta.stat().st_size / 1_048_576, 2)
            if tamanio_mb == 0:
                raise AirflowFailException(f"El archivo {ruta} está vacío.")

            print(f"Archivo de entrada listo. Ruta {ruta}, tamaño {tamanio_mb} megabytes.")
            return {"ruta": str(ruta), "tamanio_mb": tamanio_mb}

        @task(task_id="verificar_almacen", retries=5, retry_delay=timedelta(seconds=20))
        def verificar_almacen() -> bool:
            """
            Comprueba que PostgreSQL acepta conexiones antes de que el pipeline intente escribir en él.
            Por ello, se le conceden cinco reintentos cortos, puesto que el fallo más común consiste en que la base todavía esté terminando de arrancar.
            Devuelve True siempre que el almacén responda.
            Lanza AirflowFailException en caso de que la base no conteste tras agotar los reintentos.
            """
            from trabajos.carga_almacen import crear_motor, verificar_conexion
            from trabajos.configuracion import obtener_configuracion

            configuracion = obtener_configuracion()
            motor = crear_motor(configuracion.almacen)

            if not verificar_conexion(motor):
                raise AirflowFailException(
                    f"El almacén no responde en {configuracion.almacen.host}:"
                    f"{configuracion.almacen.puerto}."
                )

            print("El almacén analítico responde correctamente.")
            return True

        verificar_archivo_de_entrada()
        verificar_almacen()

    # -------------------------------------------------------------------------
    # A continuación corre el pipeline de Python, que es el que produce los datos limpios.
    # -------------------------------------------------------------------------

    @task(task_id="procesar_ventas", retries=1, retry_delay=timedelta(minutes=5))
    def procesar_ventas() -> dict[str, object]:
        """
        Corre el pipeline completo de ingesta, calidad, transformación y carga.
        La función se llama directamente en lugar de lanzar un subproceso, y la diferencia importa cuando algo falla, puesto que así la excepción original llega hasta el registro de Airflow con su rastro completo.
        Devuelve un resumen de la corrida que las tareas siguientes reciben por XCom.
        Conviene precisar que se devuelve un extracto y no el reporte entero, dado que XCom guarda todo en la base de metadatos y no conviene llenarla de datos.
        Lanza AirflowFailException siempre que el pipeline no pueda completarse por un problema en los datos de origen.
        """
        from ejecutar_pipeline import ejecutar
        from trabajos.configuracion import obtener_configuracion
        from trabajos.ingesta import ErrorDeIngesta
        from trabajos.registro import configurar_registro
        from trabajos.validaciones import ErrorDeCalidad

        configurar_registro()
        configuracion = obtener_configuracion()

        try:
            reporte = ejecutar(
                configuracion=configuracion,
                ruta_entrada=configuracion.resolver_entrada(),
                cargar_en_almacen=True,
            )
        except (ErrorDeIngesta, ErrorDeCalidad) as error:
            raise AirflowFailException(f"El pipeline se detuvo por los datos. {error}") from error

        return {
            "corrida": reporte["identificador_corrida"],
            "filas_entrada": reporte["validacion"]["filas_entrada"],
            "filas_validas": reporte["validacion"]["filas_validas"],
            "porcentaje_rechazo": reporte["validacion"]["porcentaje_rechazo"],
            "ingreso_total": reporte["metricas_negocio"]["ingreso_total"],
            "productos_distintos": reporte["metricas_negocio"]["productos_distintos"],
            "dias_cubiertos": reporte["metricas_negocio"]["dias_cubiertos"],
            "tablas_cargadas": reporte.get("carga_almacen", {}),
        }

    # -------------------------------------------------------------------------
    # Acto seguido, dbt construye las capas del almacén sobre lo que dejó el procesamiento.
    # -------------------------------------------------------------------------

    with TaskGroup(
        group_id="modelado_dbt",
        tooltip="Construye las capas del almacén y valida el resultado",
    ) as modelado_dbt:

        # Las dependencias de dbt se resuelven en una tarea aparte para que un
        # problema de red al descargar paquetes no se confunda con un error
        # de los modelos.
        instalar_dependencias_dbt = BashOperator(
            task_id="instalar_dependencias",
            bash_command=f"cd {RUTA_DBT} && {EJECUTABLE_DBT} deps --no-use-colors",
            env={"DBT_PROFILES_DIR": str(RUTA_DBT)},
            append_env=True,
            retries=3,
            retry_delay=timedelta(seconds=45),
        )

        construir_modelos = BashOperator(
            task_id="construir_modelos",
            bash_command=(
                f"cd {RUTA_DBT} && {EJECUTABLE_DBT} run --no-use-colors --target local"
            ),
            env={"DBT_PROFILES_DIR": str(RUTA_DBT)},
            append_env=True,
        )

        probar_modelos = BashOperator(
            task_id="probar_modelos",
            bash_command=(
                f"cd {RUTA_DBT} && {EJECUTABLE_DBT} test --no-use-colors --target local"
            ),
            env={"DBT_PROFILES_DIR": str(RUTA_DBT)},
            append_env=True,
        )

        # La documentación se genera al final, solo si todo lo anterior salió
        # bien. Si una etapa previa falló, esta tarea queda omitida en lugar de
        # fallar, porque una omisión no marca la corrida como fallida y el
        # problema real ya está señalado donde corresponde.
        generar_documentacion = BashOperator(
            task_id="generar_documentacion",
            bash_command=(
                f"cd {RUTA_DBT} && {EJECUTABLE_DBT} docs generate --no-use-colors --target local"
            ),
            env={"DBT_PROFILES_DIR": str(RUTA_DBT)},
            append_env=True,
            retries=0,
        )

        (
            instalar_dependencias_dbt
            >> construir_modelos
            >> probar_modelos
            >> generar_documentacion
        )

    # -------------------------------------------------------------------------
    # En paralelo con el modelado, Spark hace el análisis distribuido sobre el detalle limpio.
    # -------------------------------------------------------------------------

    analisis_distribuido = BashOperator(
        task_id="analisis_distribuido",
        bash_command=(
            # El envío se invoca por su ruta absoluta dentro de SPARK_HOME.
            # De ese modo no depende de que el intérprete que arranca la tarea sepa importar PySpark, cosa que no ocurre cuando el operador de Bash corre sin cargar el perfil de la sesión.
            "${SPARK_HOME}/bin/spark-submit "
            "--master ${SPARK_MASTER_URL} "
            "--name analisis-ventas-minoristas "
            "--conf spark.driver.host=${SPARK_DRIVER_HOST} "
            "--conf spark.driver.bindAddress=0.0.0.0 "
            "--conf spark.executor.memory=1g "
            "--conf spark.executor.cores=2 "
            "--conf spark.cores.max=2 "
            f"{RAIZ_PROYECTO}/trabajos/spark/agregado_ventas.py "
            f"--entrada {RAIZ_PROYECTO}/salida/detalle_ventas "
            f"--salida {RAIZ_PROYECTO}/salida/analitica_spark"
        ),
        env={
            "SPARK_MASTER_URL": os.environ.get("SPARK_MASTER_URL", "local[*]"),
            # El controlador corre dentro de este contenedor y los ejecutores
            # necesitan poder devolverle los resultados. Sin esta dirección,
            # Spark anuncia una IP interna que el trabajador no sabe alcanzar.
            "SPARK_DRIVER_HOST": os.environ.get("SPARK_DRIVER_HOST", "airflow-programador"),
            "PYTHONPATH": str(RAIZ_PROYECTO),
            # La imagen ya define SPARK_HOME, aunque se repite acá con el mismo valor por defecto para que el grafo siga siendo legible sin abrir el Dockerfile.
            "SPARK_HOME": os.environ.get(
                "SPARK_HOME", "/home/airflow/.local/lib/python3.12/site-packages/pyspark"
            ),
        },
        append_env=True,
        retries=1,
        retry_delay=timedelta(minutes=3),
    )

    # -------------------------------------------------------------------------
    # Por último se resume la corrida y se cierra el grafo.
    # -------------------------------------------------------------------------

    @task(task_id="resumen_de_la_corrida", trigger_rule=TriggerRule.ALL_SUCCESS)
    def resumen_de_la_corrida(resultado: dict[str, object]) -> None:
        """
        Deja los números finales en el registro de la tarea.
        Recibe en resultado el extracto que devolvió la tarea de procesamiento.
        Tener el resumen en el registro evita abrir una consola de base de datos para responder la pregunta más frecuente cuando alguien revisa una corrida, que es cuánto se procesó y cuánto dio.
        Lanza AirflowSkipException en caso de que no llegue ningún resultado por XCom, situación que solo se da si la etapa anterior quedó omitida.
        """
        if not resultado:
            raise AirflowSkipException("No llegó el resultado de la etapa de procesamiento")

        print("=" * 62)
        print("  RESUMEN DE LA CORRIDA")
        print("=" * 62)
        print(f"  Identificador       {resultado.get('corrida')}")
        print(f"  Filas leídas        {resultado.get('filas_entrada'):,}")
        print(f"  Filas válidas       {resultado.get('filas_validas'):,}")
        print(f"  Rechazo             {resultado.get('porcentaje_rechazo')} por ciento")
        print(f"  Ingreso total       {resultado.get('ingreso_total'):,.2f}")
        print(f"  Productos distintos {resultado.get('productos_distintos'):,}")
        print(f"  Días cubiertos      {resultado.get('dias_cubiertos'):,}")
        print(f"  Tablas cargadas     {resultado.get('tablas_cargadas')}")
        print("=" * 62)

    # La regla de disparo de la tarea final define el estado de toda la corrida,
    # porque Airflow lo deduce de las tareas terminales del grafo. Con ALL_DONE
    # esta tarea tendría éxito incluso si el procesamiento falló, y la corrida
    # aparecería en verde con datos que nunca se publicaron. NONE_FAILED hace lo
    # correcto, si algo aguas arriba falló, esta tarea queda en fallo heredado y
    # la corrida se marca como fallida.
    fin = EmptyOperator(task_id="fin", trigger_rule=TriggerRule.NONE_FAILED)

    # -------------------------------------------------------------------------
    # Dependencias entre etapas
    # -------------------------------------------------------------------------

    resultado_procesamiento = procesar_ventas()

    inicio >> preparacion >> resultado_procesamiento

    # dbt y Spark no dependen entre sí, los dos solo necesitan que el
    # procesamiento haya terminado. Dejarlos en paralelo acorta la corrida.
    resultado_procesamiento >> modelado_dbt
    resultado_procesamiento >> analisis_distribuido

    cierre = resumen_de_la_corrida(resultado_procesamiento)

    # El cierre se conecta a las pruebas de dbt y no al grupo completo. Si se
    # conectara al grupo, esperaría también a la generación de documentación,
    # que es una tarea accesoria y no debería retrasar el resumen.
    [probar_modelos, analisis_distribuido] >> cierre >> fin
