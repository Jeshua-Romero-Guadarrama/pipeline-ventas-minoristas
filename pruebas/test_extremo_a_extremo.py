"""
Pruebas del pipeline completo, desde la lectura del archivo hasta la salida final.
Cabe señalar que las pruebas unitarias verifican cada pieza por separado, aunque no dicen nada sobre cómo encajan entre sí.
Las pruebas reunidas aquí comprueban justamente eso, es decir, que el encadenamiento produce los archivos esperados, que los totales cierran de punta a punta y que los códigos de salida del programa son los correctos.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from ejecutar_pipeline import ejecutar, main
from trabajos.configuracion import ConfiguracionPipeline
from trabajos.persistencia import leer_parquet


@pytest.fixture
def archivo_de_entrada(configuracion_temporal: ConfiguracionPipeline) -> Path:
    """
    Escribe un archivo de entrada representativo dentro del directorio temporal del caso.
    Al respecto, incluye a propósito tres filas que van a ser rechazadas, puesto que una corrida real siempre las tiene y el pipeline debe saber convivir con ellas.
    Recibe en configuracion_temporal la configuración que apunta a carpetas descartables y devuelve la ruta del archivo CSV generado.
    El contenido son 30 filas buenas (diez días con tres productos cada uno) más las 3 defectuosas, es decir, 33 filas en total.
    """
    filas = []
    # Las filas buenas se generan como diez días con tres productos cada uno, y las cantidades van de 10 en 10 para que las sumas se puedan verificar sin calculadora.
    for dia in range(1, 11):
        for indice, producto in enumerate(["22086", "85048", "84879"], start=1):
            filas.append(
                {
                    "Invoice": f"4894{dia:02d}",
                    "StockCode": producto,
                    "Description": f"PRODUCTO DE PRUEBA {producto}",
                    "Quantity": 10 * indice,
                    "InvoiceDate": f"2009-12-{dia:02d} 10:00:00",
                    "Price": 2.0,
                    "Customer ID": 13085,
                    "Country": "UNITED KINGDOM",
                }
            )

    # A continuación se agregan tres filas que las reglas de calidad tienen que descartar, una por cantidad negativa, otra por precio fuera de rango y la última por código de producto nulo.
    filas.extend(
        [
            {
                "Invoice": "C48999",
                "StockCode": "22086",
                "Description": "DEVOLUCION",
                "Quantity": -5,
                "InvoiceDate": "2009-12-11 10:00:00",
                "Price": 2.0,
                "Customer ID": 13085,
                "Country": "UNITED KINGDOM",
            },
            {
                "Invoice": "489998",
                "StockCode": "AJUSTE",
                "Description": "CARGO ADMINISTRATIVO",
                "Quantity": 1,
                "InvoiceDate": "2009-12-11 10:00:00",
                "Price": 90_000.0,
                "Customer ID": 13085,
                "Country": "UNITED KINGDOM",
            },
            {
                "Invoice": "489997",
                "StockCode": None,
                "Description": "SIN CODIGO",
                "Quantity": 2,
                "InvoiceDate": "2009-12-11 10:00:00",
                "Price": 3.0,
                "Customer ID": 13085,
                "Country": "UNITED KINGDOM",
            },
        ]
    )

    ruta = configuracion_temporal.directorio_crudos / "ventas_minoristas.csv"
    pd.DataFrame(filas).to_csv(ruta, index=False, encoding="utf-8")
    return ruta


def test_la_corrida_completa_termina_bien(
    configuracion_temporal: ConfiguracionPipeline, archivo_de_entrada: Path
) -> None:
    """
    Comprueba que el pipeline recorre todas sus etapas y devuelve un reporte completo.
    Al respecto, de las 33 filas de entrada quedan 30 válidas y 3 rechazadas, repartidas en 3 productos distintos a lo largo de 10 días.
    """
    reporte = ejecutar(
        configuracion=configuracion_temporal,
        ruta_entrada=archivo_de_entrada,
        cargar_en_almacen=False,
    )

    assert reporte["validacion"]["filas_entrada"] == 33
    assert reporte["validacion"]["filas_validas"] == 30
    assert reporte["validacion"]["filas_rechazadas"] == 3
    assert reporte["metricas_negocio"]["productos_distintos"] == 3
    assert reporte["metricas_negocio"]["dias_cubiertos"] == 10


def test_los_totales_cierran_de_punta_a_punta(
    configuracion_temporal: ConfiguracionPipeline, archivo_de_entrada: Path
) -> None:
    """
    Comprueba que el ingreso que calcula el pipeline coincide con la cuenta hecha a mano.
    Al respecto, cada día vende 10 por 2.00 más 20 por 2.00 más 30 por 2.00, lo que da 120.00.
    En consecuencia, con diez días el total esperado asciende a 1200.00 y las unidades vendidas suman 600 (60 por día).
    """
    reporte = ejecutar(
        configuracion=configuracion_temporal,
        ruta_entrada=archivo_de_entrada,
        cargar_en_almacen=False,
    )

    assert reporte["metricas_negocio"]["ingreso_total"] == 1200.0
    assert reporte["metricas_negocio"]["unidades_vendidas"] == 600


def test_se_generan_todos_los_archivos_de_salida(
    configuracion_temporal: ConfiguracionPipeline, archivo_de_entrada: Path
) -> None:
    """
    Comprueba que cada destino declarado en la configuración termina existiendo en disco.
    Al respecto, se revisan el detalle limpio, el agregado en Parquet y en CSV, el resumen diario, el ranking de productos y el reporte de la última corrida.
    """
    ejecutar(
        configuracion=configuracion_temporal,
        ruta_entrada=archivo_de_entrada,
        cargar_en_almacen=False,
    )

    assert configuracion_temporal.ruta_detalle_limpio.exists()
    assert configuracion_temporal.ruta_agregado.exists()
    assert configuracion_temporal.ruta_agregado_csv.exists()
    assert (configuracion_temporal.directorio_salida / "resumen_diario").exists()
    assert (configuracion_temporal.directorio_salida / "ranking_productos.csv").exists()
    assert (configuracion_temporal.ruta_reportes / "reporte_ultima_corrida.json").exists()


def test_el_parquet_del_agregado_coincide_con_el_reporte(
    configuracion_temporal: ConfiguracionPipeline, archivo_de_entrada: Path
) -> None:
    """
    Comprueba que lo que quedó en disco coincide con lo que informó el reporte de la corrida.
    Puesto que el reporte es lo que se publica y el Parquet es lo que consultan los tableros, una discrepancia entre ambos dejaría a la gente mirando números que nadie puede reproducir.
    Adicionalmente, se verifica que el agregado no repite la pareja de fecha y producto.
    """
    reporte = ejecutar(
        configuracion=configuracion_temporal,
        ruta_entrada=archivo_de_entrada,
        cargar_en_almacen=False,
    )

    desde_disco = leer_parquet(configuracion_temporal.ruta_agregado)

    assert round(desde_disco["ingreso_total"].sum(), 2) == reporte["metricas_negocio"][
        "ingreso_total"
    ]
    assert not desde_disco.duplicated(subset=["fecha", "producto_id"]).any()


def test_el_detalle_queda_particionado_por_periodo(
    configuracion_temporal: ConfiguracionPipeline, archivo_de_entrada: Path
) -> None:
    """
    Comprueba que el detalle limpio queda repartido en carpetas por año y por mes.
    De ese modo, una consulta acotada a un período lee solo las particiones que le corresponden en lugar de escanear el conjunto completo.
    Dado que los datos de prueba corresponden todos a diciembre de 2009, la ruta esperada es mes=12 dentro de anio=2009.
    """
    ejecutar(
        configuracion=configuracion_temporal,
        ruta_entrada=archivo_de_entrada,
        cargar_en_almacen=False,
    )

    assert (configuracion_temporal.ruta_detalle_limpio / "anio=2009" / "mes=12").exists()


def test_las_filas_rechazadas_quedan_en_cuarentena(
    configuracion_temporal: ConfiguracionPipeline, archivo_de_entrada: Path
) -> None:
    """
    Comprueba que ningún registro descartado se pierde sin dejar rastro.
    Al respecto, la corrida deja un único archivo de cuarentena con las 3 filas rechazadas, cada una acompañada del motivo que la sacó del conjunto.
    Los tres motivos esperados son cantidad_minima, precio_en_rango y columnas_obligatorias_sin_nulos.
    """
    ejecutar(
        configuracion=configuracion_temporal,
        ruta_entrada=archivo_de_entrada,
        cargar_en_almacen=False,
    )

    archivos = list(configuracion_temporal.ruta_cuarentena.glob("rechazados_*.csv"))
    assert len(archivos) == 1

    rechazados = pd.read_csv(archivos[0])
    assert len(rechazados) == 3
    assert set(rechazados["motivo_rechazo"]) == {
        "cantidad_minima",
        "precio_en_rango",
        "columnas_obligatorias_sin_nulos",
    }


def test_el_csv_del_agregado_se_puede_abrir_en_una_planilla(
    configuracion_temporal: ConfiguracionPipeline, archivo_de_entrada: Path
) -> None:
    """
    Comprueba que la copia del agregado en CSV existe y trae las columnas que pide el enunciado.
    Dado que hay 3 productos a lo largo de 10 días, el archivo tiene que contener 30 filas.
    """
    ejecutar(
        configuracion=configuracion_temporal,
        ruta_entrada=archivo_de_entrada,
        cargar_en_almacen=False,
    )

    agregado = pd.read_csv(configuracion_temporal.ruta_agregado_csv)

    assert {"fecha", "producto_id", "ingreso_total"}.issubset(agregado.columns)
    assert len(agregado) == 30


def test_correr_dos_veces_da_el_mismo_resultado(
    configuracion_temporal: ConfiguracionPipeline, archivo_de_entrada: Path
) -> None:
    """
    Comprueba que correr el pipeline dos veces sobre la misma entrada da exactamente el mismo resultado.
    Al respecto, esa idempotencia es la que permite que Airflow reintente una tarea fallida sin que nadie limpie nada a mano.
    En consecuencia, la segunda corrida vuelve a dejar 30 filas en el agregado y no 60.
    """
    primero = ejecutar(
        configuracion=configuracion_temporal,
        ruta_entrada=archivo_de_entrada,
        cargar_en_almacen=False,
    )
    segundo = ejecutar(
        configuracion=configuracion_temporal,
        ruta_entrada=archivo_de_entrada,
        cargar_en_almacen=False,
    )

    assert primero["metricas_negocio"] == segundo["metricas_negocio"]
    assert len(leer_parquet(configuracion_temporal.ruta_agregado)) == 30


def test_el_limite_de_filas_reduce_lo_procesado(
    configuracion_temporal: ConfiguracionPipeline, archivo_de_entrada: Path
) -> None:
    """
    Comprueba que el parámetro de filas máximas recorta de verdad lo que se procesa.
    Al respecto, con el tope en 15 el reporte informa 15 filas de entrada aunque el archivo tenga 33, lo que sirve para una prueba de humo rápida sobre el conjunto completo.
    """
    reporte = ejecutar(
        configuracion=configuracion_temporal,
        ruta_entrada=archivo_de_entrada,
        filas_maximas=15,
        cargar_en_almacen=False,
    )

    assert reporte["validacion"]["filas_entrada"] == 15


def test_la_linea_de_comandos_devuelve_cero_cuando_todo_sale_bien(
    configuracion_temporal: ConfiguracionPipeline, archivo_de_entrada: Path
) -> None:
    """
    Comprueba que la línea de comandos devuelve cero cuando la corrida termina bien.
    Puesto que el código de salida es lo único que mira Airflow para decidir si la tarea falló, un cero equivocado marcaría en verde una corrida que no publicó nada.
    """
    codigo = main(
        [
            "--entrada",
            str(archivo_de_entrada),
            "--sin-almacen",
            "--sin-metricas",
            "--formato-log",
            "texto",
        ]
    )

    assert codigo == 0


def test_la_linea_de_comandos_devuelve_uno_ante_un_problema_de_datos(
    configuracion_temporal: ConfiguracionPipeline, tmp_path: Path
) -> None:
    """
    Comprueba que un archivo de entrada inexistente devuelve el código 1 y no una traza sin controlar.
    De ese modo, un problema de datos queda distinguido de un error de programación, que reservaría un código de salida distinto.
    """
    codigo = main(
        [
            "--entrada",
            str(tmp_path / "este_archivo_no_existe.csv"),
            "--sin-almacen",
            "--sin-metricas",
        ]
    )

    assert codigo == 1
