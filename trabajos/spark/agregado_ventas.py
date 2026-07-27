"""
El presente módulo contiene el trabajo distribuido de PySpark sobre el detalle de ventas.
Al respecto, responde preguntas que en pandas se vuelven incómodas cuando el volumen crece, sobre todo aquellas que necesitan funciones de ventana sobre el histórico completo.

En primer lugar se calcula el ranking de productos por mes mediante una ventana particionada, que permite saber qué se vendió más en cada período sin traer todo a memoria.
A continuación se calcula la media móvil de siete días del ingreso diario, que suaviza el ruido del fin de semana y deja visible la tendencia real.
Por último se calcula la concentración de ingresos por país, que en este conjunto de datos resulta fuertemente asimétrica y conviene tener medida.

El trabajo se ejecuta con spark-submit contra el clúster que define docker-compose, o bien en modo local cuando alcanza con una sola máquina.
Conviene precisar que el maestro se elige con la variable de entorno SPARK_MASTER_URL y no está escrito en el código, de manera que el mismo módulo sirve en ambos escenarios.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F
from pyspark.sql.types import DecimalType

# Cuando el módulo se lanza con spark-submit, la raíz del proyecto no queda en la ruta de importación de Python y los módulos propios no se encuentran.
# Por ello se agrega a mano antes de importarlos, que es la razón de que la importación siguiente aparezca fuera de la cabecera del archivo.
RAIZ = Path(__file__).resolve().parent.parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from trabajos.registro import configurar_registro, obtener_registrador  # noqa: E402

registrador = obtener_registrador(__name__)


def crear_sesion(nombre: str, maestro: str, particiones_barajado: int) -> SparkSession:
    """
    Levanta la sesión de Spark con la configuración del proyecto.
    El valor por defecto de particiones de barajado en Spark es doscientos, un número pensado para clústeres grandes.
    Con el volumen de este conjunto de datos esa cifra genera cientos de archivos diminutos y el costo de coordinarlos supera al del cálculo, motivo por el cual bajarla es la optimización que más se nota aquí.
    Recibe el nombre con el que la aplicación aparece en la interfaz de Spark, la URL del maestro (por ejemplo spark://spark-maestro:7077 o local[*]) y la cantidad de particiones que se conservan tras cada barajado.
    Devuelve la sesión de Spark ya configurada.
    """
    constructor = (
        SparkSession.builder.appName(nombre)
        .master(maestro)
        .config("spark.sql.shuffle.partitions", str(particiones_barajado))
        .config("spark.sql.adaptive.enabled", "true")
        .config("spark.sql.adaptive.coalescePartitions.enabled", "true")
        .config("spark.sql.parquet.compression.codec", "zstd")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.ui.showConsoleProgress", "false")
    )

    # En modo clúster el ejecutor necesita saber a qué dirección devolverle los resultados al controlador, y dentro de Docker esa dirección no se deduce sola.
    host_controlador = os.environ.get("SPARK_DRIVER_HOST", "").strip()
    if host_controlador:
        constructor = constructor.config("spark.driver.host", host_controlador).config(
            "spark.driver.bindAddress", "0.0.0.0"
        )

    sesion = constructor.getOrCreate()
    sesion.sparkContext.setLogLevel("WARN")
    return sesion


def leer_detalle(sesion: SparkSession, ruta: str) -> DataFrame:
    """
    Lee el detalle de ventas que dejó la etapa de persistencia.
    Recibe la sesión activa de Spark y la ruta de la carpeta Parquet donde quedó el detalle limpio.
    Devuelve un DataFrame distribuido con los tipos ya ajustados.
    """
    detalle = sesion.read.parquet(ruta)

    # El importe se pasa a decimal con escala fija, en razón de que en los cálculos monetarios el punto flotante acumula error al sumar muchas filas y los totales terminan por no coincidir con los del sistema contable.
    detalle = detalle.withColumn(
        "ingreso_total", F.col("ingreso_total").cast(DecimalType(18, 2))
    ).withColumn("fecha", F.to_date(F.col("fecha")))

    registrador.info("Detalle leído desde Parquet", extra={"ruta": ruta})
    return detalle


def ranking_mensual_por_producto(detalle: DataFrame, posiciones: int = 10) -> DataFrame:
    """
    Calcula los productos más vendidos de cada mes.
    Para ello usa una función de ventana particionada por mes, que constituye exactamente el caso donde Spark aporta sobre una solución de una sola máquina, puesto que cada partición se ordena en paralelo en un ejecutor distinto.
    Recibe el detalle de ventas a nivel de línea de factura y la cantidad de productos que se conservan por mes.
    Devuelve un DataFrame con el ranking mensual y la participación de cada producto en el ingreso de su período.
    """
    por_mes = (
        detalle.withColumn("anio_mes", F.date_format(F.col("fecha"), "yyyy-MM"))
        .groupBy("anio_mes", "producto_id")
        .agg(
            F.sum("ingreso_total").alias("ingreso_total"),
            F.sum("cantidad").alias("unidades_vendidas"),
            F.countDistinct("factura").alias("facturas_distintas"),
            F.first("descripcion", ignorenulls=True).alias("descripcion_producto"),
        )
    )

    ventana_ranking = Window.partitionBy("anio_mes").orderBy(F.col("ingreso_total").desc())
    ventana_total = Window.partitionBy("anio_mes")

    resultado = (
        por_mes.withColumn("posicion", F.row_number().over(ventana_ranking))
        .withColumn("ingreso_del_mes", F.sum("ingreso_total").over(ventana_total))
        .filter(F.col("posicion") <= posiciones)
        .withColumn(
            "participacion_porcentual",
            F.round(F.col("ingreso_total") / F.col("ingreso_del_mes") * 100, 3),
        )
        .drop("ingreso_del_mes")
        .orderBy("anio_mes", "posicion")
    )

    return resultado


def tendencia_movil_diaria(detalle: DataFrame, ventana_dias: int = 7) -> DataFrame:
    """
    Calcula el ingreso diario y su media móvil.
    La media móvil se apoya en una ventana definida sobre días de calendario y no sobre cantidad de filas.
    La distinción importa porque el comercio no factura todos los días, de modo que una ventana por filas mezclaría períodos de duración distinta según cuántos días hábiles hubo en cada uno.
    Recibe el detalle de ventas a nivel de línea de factura y la amplitud de la ventana móvil expresada en días.
    Devuelve un DataFrame con una fila por día, su ingreso y la media móvil correspondiente.
    """
    diario = detalle.groupBy("fecha").agg(
        F.sum("ingreso_total").alias("ingreso_total"),
        F.sum("cantidad").alias("unidades_vendidas"),
        F.countDistinct("factura").alias("facturas_distintas"),
        F.countDistinct("producto_id").alias("productos_distintos"),
    )

    # La fecha se convierte a segundos, dado que una ventana por rango solo admite un desplazamiento numérico y de ese modo la amplitud se puede expresar en días de calendario.
    segundos_por_dia = 86_400
    ventana = (
        Window.orderBy(F.col("fecha_en_segundos"))
        .rangeBetween(-(ventana_dias - 1) * segundos_por_dia, 0)
    )

    resultado = (
        diario.withColumn("fecha_en_segundos", F.unix_timestamp(F.col("fecha")))
        .withColumn(
            "ingreso_media_movil",
            F.round(F.avg(F.col("ingreso_total").cast("double")).over(ventana), 2),
        )
        .withColumn(
            "ingreso_acumulado",
            F.sum(F.col("ingreso_total").cast("double")).over(
                Window.orderBy("fecha_en_segundos").rowsBetween(
                    Window.unboundedPreceding, Window.currentRow
                )
            ),
        )
        .drop("fecha_en_segundos")
        .orderBy("fecha")
    )

    return resultado


def concentracion_por_pais(detalle: DataFrame) -> DataFrame:
    """
    Mide cuánto aporta cada país al ingreso total.
    Recibe el detalle de ventas a nivel de línea de factura.
    Devuelve un DataFrame ordenado por ingreso, con la participación individual y la acumulada de cada país.
    En caso de que el detalle no traiga la columna de país, el resultado es un DataFrame vacío y el motivo queda anotado en el log.
    """
    if "pais" not in detalle.columns:
        registrador.warning(
            "El detalle no incluye la columna de país, motivo por el cual se omite el análisis de concentración"
        )
        return detalle.sparkSession.createDataFrame([], schema="pais string")

    por_pais = detalle.groupBy("pais").agg(
        F.sum("ingreso_total").alias("ingreso_total"),
        F.countDistinct("factura").alias("facturas_distintas"),
        F.countDistinct("producto_id").alias("productos_distintos"),
    )

    total_general = por_pais.agg(F.sum("ingreso_total").alias("total")).collect()[0]["total"]
    ventana_acumulada = Window.orderBy(F.col("ingreso_total").desc()).rowsBetween(
        Window.unboundedPreceding, Window.currentRow
    )

    resultado = (
        por_pais.withColumn(
            "participacion_porcentual",
            F.round(F.col("ingreso_total") / F.lit(total_general) * 100, 3),
        )
        .withColumn(
            "participacion_acumulada",
            F.round(F.sum("participacion_porcentual").over(ventana_acumulada), 3),
        )
        .orderBy(F.col("ingreso_total").desc())
    )

    return resultado


def escribir(resultado: DataFrame, destino: Path, nombre: str) -> None:
    """
    Guarda en Parquet un resultado del trabajo distribuido.
    Antes de escribir se reduce todo a una sola partición, puesto que los resultados agregados son pequeños y muchos archivos diminutos perjudican la lectura posterior más de lo que aporta el paralelismo en la escritura.
    Recibe el DataFrame que se desea persistir, la carpeta base donde se agrupan las salidas del trabajo y el nombre de la subcarpeta que identifica al resultado.
    """
    ruta = destino / nombre
    resultado.coalesce(1).write.mode("overwrite").parquet(str(ruta))
    registrador.info("Resultado de Spark escrito", extra={"ruta": str(ruta)})


def analizar_argumentos(argumentos: list[str] | None = None) -> argparse.Namespace:
    """
    Define y lee los parámetros de línea de comandos del trabajo.
    Recibe la lista de argumentos que se desea analizar, de modo que en caso de que se omita se toman los de sys.argv.
    Devuelve un espacio de nombres con los parámetros ya resueltos.
    """
    analizador = argparse.ArgumentParser(
        description="Análisis distribuido del detalle de ventas con PySpark"
    )
    analizador.add_argument(
        "--entrada",
        default=str(RAIZ / "salida" / "detalle_ventas"),
        help="Carpeta Parquet que contiene el detalle limpio de ventas",
    )
    analizador.add_argument(
        "--salida",
        default=str(RAIZ / "salida" / "analitica_spark"),
        help="Carpeta donde se escriben los resultados del análisis",
    )
    analizador.add_argument(
        "--maestro",
        default=os.environ.get("SPARK_MASTER_URL", "local[*]"),
        help="URL del maestro de Spark contra el que se ejecuta el trabajo",
    )
    analizador.add_argument(
        "--particiones",
        type=int,
        default=int(os.environ.get("SPARK_PARTICIONES_BARAJADO", "8")),
        help="Cantidad de particiones que se conservan tras cada barajado",
    )
    analizador.add_argument(
        "--posiciones",
        type=int,
        default=10,
        help="Cantidad de productos que se conservan en el ranking mensual",
    )
    return analizador.parse_args(argumentos)


def main(argumentos: list[str] | None = None) -> int:
    """
    Punto de entrada del trabajo distribuido.
    Recibe los argumentos de línea de comandos, lo que resulta útil para las pruebas, y en caso de que se omitan se toman los de sys.argv.
    Devuelve cero cuando el análisis terminó bien y uno cuando se interrumpió por un error.
    """
    configurar_registro()
    opciones = analizar_argumentos(argumentos)

    registrador.info(
        "Iniciando análisis distribuido",
        extra={
            "entrada": opciones.entrada,
            "salida": opciones.salida,
            "maestro": opciones.maestro,
        },
    )

    sesion = crear_sesion(
        nombre="analisis-ventas-minoristas",
        maestro=opciones.maestro,
        particiones_barajado=opciones.particiones,
    )

    try:
        detalle = leer_detalle(sesion, opciones.entrada)
        # El detalle se recorre tres veces, una por cada análisis.
        # Por ello se guarda en memoria, con el fin de no releer el Parquet completo en cada recorrido.
        detalle.cache()
        filas = detalle.count()
        registrador.info("Detalle cargado en memoria", extra={"filas": filas})

        destino = Path(opciones.salida)

        ranking = ranking_mensual_por_producto(detalle, opciones.posiciones)
        escribir(ranking, destino, "ranking_mensual_productos")

        tendencia = tendencia_movil_diaria(detalle)
        escribir(tendencia, destino, "tendencia_diaria")

        paises = concentracion_por_pais(detalle)
        escribir(paises, destino, "concentracion_por_pais")

        registrador.info(
            "Análisis distribuido finalizado",
            extra={
                "filas_procesadas": filas,
                "meses_en_ranking": ranking.select("anio_mes").distinct().count(),
                "dias_en_tendencia": tendencia.count(),
            },
        )
        return 0
    except Exception as error:  # noqa: BLE001
        registrador.exception("El análisis distribuido falló", extra={"detalle": str(error)})
        return 1
    finally:
        sesion.stop()


if __name__ == "__main__":
    raise SystemExit(main())
