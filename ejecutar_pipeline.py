"""
El presente archivo constituye el punto de entrada único del pipeline de ventas.
Al respecto, encadena las etapas en el orden correcto y se ocupa de que cada corrida resulte reproducible.
Toda la lógica de negocio reside en el paquete trabajos, motivo por el cual aquí solo se coordina, se mide y se decide qué hacer cuando algo falla.

A continuación se muestran las formas habituales de invocarlo desde la línea de comandos.

    python ejecutar_pipeline.py
    python ejecutar_pipeline.py --entrada datos/ejemplos/ventas_minoristas_muestra.csv
    python ejecutar_pipeline.py --filas-maximas 50000 --sin-almacen
    python ejecutar_pipeline.py --formato-log texto
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from trabajos import __version__
from trabajos.carga_almacen import cargar_resultados
from trabajos.configuracion import ConfiguracionPipeline, obtener_configuracion
from trabajos.ingesta import ErrorDeIngesta, leer_archivo, resumir_ingesta
from trabajos.metricas import RecolectorMetricas, medir_etapa
from trabajos.persistencia import (
    guardar_csv,
    guardar_cuarentena,
    guardar_parquet,
    guardar_reporte,
)
from trabajos.registro import configurar_registro, obtener_registrador
from trabajos.transformaciones import (
    agregar_por_producto_y_fecha,
    agregar_resumen_diario,
    calcular_ingreso_total,
    enriquecer_con_calendario,
    ranking_de_productos,
)
from trabajos.validaciones import ErrorDeCalidad, validar, verificar_agregado

registrador = obtener_registrador("pipeline")


def analizar_argumentos(argumentos: list[str] | None = None) -> argparse.Namespace:
    """
    Define los parámetros de línea de comandos del pipeline.
    Recibe la lista de argumentos que se desea analizar, de modo que en caso de que se omita se toman los de sys.argv.
    Devuelve un espacio de nombres con las opciones ya resueltas.
    """
    analizador = argparse.ArgumentParser(
        prog="ejecutar_pipeline.py",
        description=(
            "Ejecuta el pipeline completo de ventas minoristas, desde la lectura "
            "del archivo crudo hasta la publicación de los resultados agregados."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    analizador.add_argument(
        "--entrada",
        type=Path,
        default=None,
        help="Archivo de entrada que se desea procesar. En caso de que se omita, la ruta se resuelve desde la configuración.",
    )
    analizador.add_argument(
        "--filas-maximas",
        type=int,
        default=None,
        help="Limita la cantidad de filas que se leen del archivo de entrada (resulta útil para una prueba rápida).",
    )
    analizador.add_argument(
        "--sin-almacen",
        action="store_true",
        help="Omite la carga en PostgreSQL, de manera que los resultados quedan únicamente en los archivos de disco.",
    )
    analizador.add_argument(
        "--sin-metricas",
        action="store_true",
        help="Desactiva la publicación de métricas hacia Prometheus.",
    )
    analizador.add_argument(
        "--formato-log",
        choices=["json", "texto"],
        default=None,
        help="Formato con el que se escriben los mensajes de log en la salida.",
    )
    analizador.add_argument(
        "--nivel-log",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default=None,
        help="Nivel mínimo que debe alcanzar un mensaje para que quede registrado.",
    )
    return analizador.parse_args(argumentos)


def _marca_de_corrida() -> str:
    """
    Genera el identificador de una corrida a partir de la hora UTC del momento.
    Devuelve una cadena con el formato AAAAMMDD-HHMMSS, cuyo orden alfabético coincide con el cronológico y permite listar las corridas sin interpretar la fecha.
    """
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S")


def ejecutar(
    configuracion: ConfiguracionPipeline,
    ruta_entrada: Path,
    filas_maximas: int | None = None,
    cargar_en_almacen: bool = True,
) -> dict[str, object]:
    """
    Corre el pipeline completo y devuelve el reporte de la ejecución.
    El orden de las etapas es el que dicta la dependencia entre ellas, de manera que primero se lee, después se valida, a continuación se transforma, luego se comprueba el resultado y solo entonces se publica.
    Conviene precisar que nada se escribe en el destino final antes de que el agregado supere sus verificaciones, con el fin de no dejar datos incorrectos a la vista de los tableros.
    Recibe la configuración con las rutas, los umbrales y las conexiones, junto con la ruta del archivo crudo que se va a procesar.
    Admite además un límite opcional de filas a leer y un indicador que, cuando vale False, omite la carga en PostgreSQL.
    Devuelve un diccionario con el reporte completo de la corrida.
    Lanza ErrorDeIngesta en caso de que el archivo de entrada no se pueda leer, y ErrorDeCalidad cuando los datos no alcanzan el nivel mínimo exigido.
    """
    marca = _marca_de_corrida()
    configuracion.preparar_directorios()

    recolector = RecolectorMetricas(configuracion=configuracion.metricas)
    reporte: dict[str, object] = {
        "identificador_corrida": marca,
        "version_pipeline": __version__,
        "archivo_entrada": str(ruta_entrada),
        "inicio": datetime.now(UTC).isoformat(),
    }

    registrador.info(
        "Arranca la corrida del pipeline",
        extra={"corrida": marca, "entrada": str(ruta_entrada), "version": __version__},
    )

    # La primera etapa lee el archivo crudo por lotes, de modo que la memoria ocupada durante la lectura no dependa del tamaño total del archivo.
    with medir_etapa(recolector, "ingesta"):
        crudo = leer_archivo(
            ruta_entrada,
            filas_maximas=filas_maximas,
            tamanio_lote=configuracion.tamanio_lote_ingesta,
        )
    reporte["ingesta"] = resumir_ingesta(crudo)
    recolector.registrar_filas("ingesta", len(crudo))

    # La segunda etapa aplica las reglas de calidad y aparta las filas rechazadas, que se guardan en cuarentena para poder auditarlas después.
    with medir_etapa(recolector, "validacion"):
        resultado_validacion = validar(crudo, configuracion)
    reporte["validacion"] = resultado_validacion.a_diccionario()
    recolector.registrar_filas("validacion", resultado_validacion.filas_validas)
    for regla, cantidad in resultado_validacion.conteo_por_regla.items():
        recolector.registrar_rechazos(regla, cantidad)

    ruta_cuarentena = guardar_cuarentena(
        resultado_validacion.rechazados, configuracion.ruta_cuarentena, marca
    )
    reporte["archivo_cuarentena"] = str(ruta_cuarentena) if ruta_cuarentena else None

    # La tabla cruda ya cumplió su función una vez terminada la validación.
    # Liberarla en este punto importa, en razón de que ocupa varios cientos de megabytes que de otro modo convivirían en memoria con las tablas de las etapas siguientes.
    del crudo

    # La tercera etapa aplica las transformaciones de negocio sobre las filas que superaron la validación.
    with medir_etapa(recolector, "transformacion"):
        # A las dos funciones se les pide que escriban sobre la tabla recibida en lugar de copiarla.
        # Hacerlo resulta seguro aquí, puesto que el orquestador es dueño de esos datos y nadie más los va a consultar después.
        # Con un millón de filas, cada copia evitada representa varios cientos de megabytes que dejan de convivir en memoria.
        detalle = calcular_ingreso_total(resultado_validacion.validos, copiar=False)
        detalle = enriquecer_con_calendario(detalle, copiar=False)

        # El resultado de la validación mantiene vivas dos referencias más a los datos, una con las filas válidas y otra con las rechazadas.
        # Las rechazadas ya se escribieron en cuarentena y las válidas están dentro de detalle, motivo por el cual ninguna de las dos hace falta.
        resultado_validacion.validos = pd.DataFrame()
        resultado_validacion.rechazados = pd.DataFrame()

        agregado = agregar_por_producto_y_fecha(detalle)
        resumen_diario = agregar_resumen_diario(agregado)
        ranking = ranking_de_productos(agregado, cantidad=25)

    recolector.registrar_filas("transformacion", len(detalle))
    recolector.registrar_filas("agregacion", len(agregado))

    # La cuarta etapa verifica el agregado antes de publicarlo, dado que un resultado incorrecto a la vista de los tableros cuesta bastante más que una corrida detenida a tiempo.
    with medir_etapa(recolector, "verificacion_salida"):
        reporte["verificacion_agregado"] = verificar_agregado(agregado)

    # La quinta etapa deja los resultados en disco, que es la salida de la que se sirven dbt y los cuadernos de análisis.
    with medir_etapa(recolector, "persistencia"):
        # La tabla detalle ya trae los atributos de calendario desde la etapa anterior.
        # Por ello no se vuelven a derivar aquí, puesto que hacerlo crearía una copia completa de la tabla en memoria para obtener exactamente el mismo resultado.
        guardar_parquet(
            detalle,
            configuracion.ruta_detalle_limpio,
            columnas_particion=["anio", "mes"],
        )
        guardar_parquet(agregado, configuracion.ruta_agregado)
        guardar_csv(agregado, configuracion.ruta_agregado_csv)
        guardar_parquet(resumen_diario, configuracion.directorio_salida / "resumen_diario")
        guardar_csv(ranking, configuracion.directorio_salida / "ranking_productos.csv")

    reporte["salidas"] = {
        "detalle_ventas": str(configuracion.ruta_detalle_limpio),
        "ingresos_por_producto_fecha": str(configuracion.ruta_agregado),
        "ingresos_por_producto_fecha_csv": str(configuracion.ruta_agregado_csv),
        "resumen_diario": str(configuracion.directorio_salida / "resumen_diario"),
        "ranking_productos": str(configuracion.directorio_salida / "ranking_productos.csv"),
    }

    # La sexta etapa carga los resultados en el almacén analítico, siempre que quien ejecuta el pipeline no haya pedido lo contrario.
    if cargar_en_almacen:
        with medir_etapa(recolector, "carga_almacen"):
            reporte["carga_almacen"] = cargar_resultados(
                detalle, agregado, resumen_diario, configuracion.almacen
            )
    else:
        registrador.info("Carga al almacén omitida por parámetro de línea de comandos")
        reporte["carga_almacen"] = {}

    # Las métricas que siguen son las de negocio, es decir, las que alimentan el tablero de Grafana y no el diagnóstico técnico de la corrida.
    ingreso_total = float(agregado["ingreso_total"].sum())
    recolector.registrar_valor("pipeline_ventas_ingreso_total", round(ingreso_total, 2))
    recolector.registrar_valor(
        "pipeline_ventas_productos_distintos", float(agregado["producto_id"].nunique())
    )
    recolector.registrar_valor(
        "pipeline_ventas_dias_cubiertos", float(agregado["fecha"].nunique())
    )
    recolector.registrar_valor(
        "pipeline_ventas_porcentaje_rechazo", resultado_validacion.porcentaje_rechazo
    )

    reporte["metricas_negocio"] = {
        "ingreso_total": round(ingreso_total, 2),
        "ticket_promedio_por_linea": round(float(detalle["ingreso_total"].mean()), 2),
        "productos_distintos": int(agregado["producto_id"].nunique()),
        "dias_cubiertos": int(agregado["fecha"].nunique()),
        "fecha_minima": str(agregado["fecha"].min()),
        "fecha_maxima": str(agregado["fecha"].max()),
        "unidades_vendidas": int(agregado["unidades_vendidas"].sum()),
    }
    reporte["muestra_agregado"] = (
        agregado.head(10).astype(str).to_dict(orient="records")
    )
    reporte["fin"] = datetime.now(UTC).isoformat()

    recolector.registrar_resultado(exitoso=True)
    recolector.publicar()

    ruta_reporte = configuracion.ruta_reportes / f"reporte_{marca}.json"
    guardar_reporte(reporte, ruta_reporte)
    guardar_reporte(reporte, configuracion.ruta_reportes / "reporte_ultima_corrida.json")
    reporte["archivo_reporte"] = str(ruta_reporte)

    registrador.info(
        "Pipeline finalizado correctamente",
        extra={
            "corrida": marca,
            "filas_entrada": resultado_validacion.filas_entrada,
            "filas_agregado": int(len(agregado)),
            "ingreso_total": round(ingreso_total, 2),
        },
    )
    return reporte


def _mostrar_resumen(reporte: dict[str, object]) -> None:
    """
    Imprime en pantalla un resumen legible de la corrida.
    Los logs en formato JSON resultan excelentes para una máquina y bastante incómodos para una persona que mira la terminal, de ahí que al final se escriba este resumen.
    Recibe el reporte que devuelve la función ejecutar.
    """
    validacion = reporte.get("validacion", {})
    negocio = reporte.get("metricas_negocio", {})

    lineas = [
        "",
        "=" * 68,
        "  RESUMEN DE LA CORRIDA DEL PIPELINE DE VENTAS",
        "=" * 68,
        f"  Corrida            {reporte.get('identificador_corrida')}",
        f"  Archivo de entrada {reporte.get('archivo_entrada')}",
        "-" * 68,
        f"  Filas leídas       {validacion.get('filas_entrada', 0):,}",
        f"  Filas válidas      {validacion.get('filas_validas', 0):,}",
        f"  Filas rechazadas   {validacion.get('filas_rechazadas', 0):,} "
        f"({validacion.get('porcentaje_rechazo', 0)} por ciento)",
        "-" * 68,
        f"  Ingreso total      {negocio.get('ingreso_total', 0):,.2f}",
        f"  Unidades vendidas  {negocio.get('unidades_vendidas', 0):,}",
        f"  Productos          {negocio.get('productos_distintos', 0):,}",
        f"  Días cubiertos     {negocio.get('dias_cubiertos', 0):,}",
        f"  Período            {negocio.get('fecha_minima')} a {negocio.get('fecha_maxima')}",
        "-" * 68,
        f"  Reporte JSON       {reporte.get('archivo_reporte')}",
        "=" * 68,
        "",
    ]
    print("\n".join(lineas))

    muestra = reporte.get("muestra_agregado")
    if muestra:
        print("  Primeras filas del agregado por fecha y producto")
        print(pd.DataFrame(muestra).to_string(index=False))
        print()


def main(argumentos: list[str] | None = None) -> int:
    """
    Punto de entrada de la línea de comandos.
    Recibe la lista de argumentos que se desea procesar, lo que resulta útil para las pruebas, y en caso de que se omita se toman los de sys.argv.
    Devuelve cero cuando la corrida terminó bien, uno cuando se detuvo por un problema en los datos y dos cuando falló por un error inesperado.
    """
    opciones = analizar_argumentos(argumentos)
    # Aquí sí corresponde tomar el control del registro, en razón de que este es el punto de entrada del programa y no hay ninguna otra aplicación que lo comparta.
    configurar_registro(nivel=opciones.nivel_log, formato=opciones.formato_log, forzar=True)

    configuracion = obtener_configuracion()
    ruta_entrada = opciones.entrada or configuracion.resolver_entrada()

    if opciones.sin_metricas:
        # La configuración de métricas es inmutable, motivo por el cual la publicación se desactiva escribiendo el atributo directamente y el resto de los parámetros queda intacto.
        object.__setattr__(configuracion.metricas, "habilitado", False)

    try:
        reporte = ejecutar(
            configuracion=configuracion,
            ruta_entrada=Path(ruta_entrada),
            filas_maximas=opciones.filas_maximas,
            cargar_en_almacen=not opciones.sin_almacen,
        )
    except (ErrorDeIngesta, ErrorDeCalidad) as error:
        registrador.error("El pipeline se detuvo por un problema de datos", extra={"detalle": str(error)})
        print(
            f"\nLa corrida se detuvo porque los datos no cumplen lo que exige alguna de sus etapas. {error}\n"
            "Se sugiere revisar el archivo de entrada y los umbrales de calidad definidos en la configuración antes de volver a ejecutarlo.\n",
            file=sys.stderr,
        )
        return 1
    except Exception as error:  # noqa: BLE001
        registrador.exception("El pipeline falló por un error inesperado", extra={"detalle": str(error)})
        print(
            f"\nLa corrida terminó por un error inesperado, ajeno a las reglas de calidad de los datos. {error}\n"
            "En el log queda la traza completa, que constituye el punto de partida para diagnosticarlo.\n",
            file=sys.stderr,
        )
        return 2

    _mostrar_resumen(reporte)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
