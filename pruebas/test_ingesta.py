"""
Pruebas de la etapa de ingesta.
Lo que se busca comprobar acá es que la ingesta cumple su contrato: Traduce los encabezados originales, fuerza los tipos correctos y avisa con un error claro cuando el archivo no sirve.
En cambio, no se comprueba la calidad de los datos, puesto que esa responsabilidad corresponde a otro módulo.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from trabajos.ingesta import (
    ErrorDeIngesta,
    leer_archivo,
    resumir_ingesta,
    verificar_columnas,
)


def test_lee_csv_y_traduce_los_encabezados(csv_de_prueba: Path) -> None:
    """
    Comprueba que un archivo con encabezados en inglés queda con los nombres de columna del proyecto.
    Al respecto, las ocho columnas del origen se traducen sin perder ninguna y las cinco filas del archivo se leen completas.
    """
    resultado = leer_archivo(csv_de_prueba)

    esperadas = {
        "factura",
        "producto_id",
        "descripcion",
        "cantidad",
        "fecha_hora",
        "precio_unitario",
        "cliente_id",
        "pais",
    }
    assert esperadas.issubset(set(resultado.columns))
    assert len(resultado) == 5


def test_deriva_la_columna_fecha_desde_la_marca_de_tiempo(csv_de_prueba: Path) -> None:
    """
    Comprueba que la columna de fecha sin hora se deriva de la marca de tiempo completa.
    Al respecto, la primera fila tiene fecha_hora igual a 2009-12-01 07:45:00, motivo por el cual su fecha resulta 2009-12-01.
    Dado que la agregación se hace por día, esa columna derivada es la que evita agrupar por hora sin querer.
    """
    resultado = leer_archivo(csv_de_prueba)

    assert "fecha" in resultado.columns
    assert resultado["fecha"].notna().all()
    assert str(resultado["fecha"].iloc[0]) == "2009-12-01"


def test_asigna_los_tipos_correctos(csv_de_prueba: Path) -> None:
    """
    Comprueba que cada columna termina con el tipo que espera el resto del pipeline.
    Al respecto, la cantidad queda como entero, el precio como flotante, la marca de tiempo como fecha y el código de producto como texto.
    Conviene precisar que el código se conserva como texto porque valores como 85123A dejarían de leerse si se forzara a número.
    """
    resultado = leer_archivo(csv_de_prueba)

    assert pd.api.types.is_integer_dtype(resultado["cantidad"])
    assert pd.api.types.is_float_dtype(resultado["precio_unitario"])
    assert pd.api.types.is_datetime64_any_dtype(resultado["fecha_hora"])
    assert pd.api.types.is_string_dtype(resultado["producto_id"])


def test_normaliza_el_texto_de_las_columnas_de_identificacion(tmp_path: Path) -> None:
    """
    Comprueba que la ingesta limpia los espacios sobrantes y unifica las mayúsculas de las columnas de identificación.
    Al respecto, " 85123a " queda como "85123A", "  489434 " queda como "489434" y "united kingdom" queda como "UNITED KINGDOM".
    Puesto que esas columnas son claves de agrupación, dos escrituras distintas del mismo código producirían dos filas donde debería haber una.
    """
    origen = pd.DataFrame(
        {
            "Invoice": ["  489434 "],
            "StockCode": [" 85123a "],
            "Description": ["producto de prueba"],
            "Quantity": [3],
            "InvoiceDate": ["2009-12-01 10:00:00"],
            "Price": [1.5],
            "Customer ID": [13085],
            "Country": ["united kingdom"],
        }
    )
    ruta = tmp_path / "con_espacios.csv"
    origen.to_csv(ruta, index=False)

    resultado = leer_archivo(ruta)

    assert resultado["producto_id"].iloc[0] == "85123A"
    assert resultado["factura"].iloc[0] == "489434"
    assert resultado["pais"].iloc[0] == "UNITED KINGDOM"


def test_los_valores_no_numericos_quedan_como_nulos(tmp_path: Path) -> None:
    """
    Comprueba que un texto colocado en una columna numérica no corta la lectura.
    Al respecto, la cantidad "diez" de la primera fila y el precio "sin precio" de la segunda quedan como nulos, mientras las dos filas se conservan.
    Conviene precisar que se prefiere ese comportamiento antes que abortar la corrida entera por una fila, ya que la capa de calidad la rechazará después dejando constancia del motivo.
    """
    origen = pd.DataFrame(
        {
            "Invoice": ["489434", "489435"],
            "StockCode": ["22086", "22087"],
            "Description": ["uno", "dos"],
            "Quantity": ["diez", 5],
            "InvoiceDate": ["2009-12-01 10:00:00", "2009-12-01 11:00:00"],
            "Price": [2.5, "sin precio"],
            "Customer ID": [13085, 13078],
            "Country": ["UNITED KINGDOM", "UNITED KINGDOM"],
        }
    )
    ruta = tmp_path / "valores_sucios.csv"
    origen.to_csv(ruta, index=False)

    resultado = leer_archivo(ruta)

    assert len(resultado) == 2
    assert pd.isna(resultado["cantidad"].iloc[0])
    assert pd.isna(resultado["precio_unitario"].iloc[1])


def test_respeta_el_limite_de_filas(csv_de_prueba: Path) -> None:
    """
    Comprueba que el parámetro de filas máximas recorta la lectura.
    Al respecto, el archivo tiene 5 filas y con el tope en 2 se leen únicamente las 2 primeras.
    """
    resultado = leer_archivo(csv_de_prueba, filas_maximas=2)
    assert len(resultado) == 2


def test_avisa_cuando_el_archivo_no_existe(tmp_path: Path) -> None:
    """
    Comprueba que un archivo inexistente produce el error propio del módulo con un mensaje explicativo.
    De ese modo, quien lea el registro sabe que falta el archivo en lugar de encontrarse con una traza de la biblioteca de lectura.
    """
    with pytest.raises(ErrorDeIngesta, match="No se encontró el archivo"):
        leer_archivo(tmp_path / "no_existe.csv")


def test_avisa_cuando_el_formato_no_esta_soportado(tmp_path: Path) -> None:
    """
    Comprueba que una extensión no contemplada produce un error explicativo antes de intentar leer nada.
    Al respecto, se prueba con un archivo .xlsx, formato que el proyecto no admite porque toda la entrada llega en CSV o en Parquet.
    """
    ruta = tmp_path / "datos.xlsx"
    ruta.write_bytes(b"contenido cualquiera")

    with pytest.raises(ErrorDeIngesta, match="Formato de archivo no soportado"):
        leer_archivo(ruta)


def test_avisa_cuando_el_archivo_esta_vacio(tmp_path: Path) -> None:
    """
    Comprueba que un archivo con encabezados pero sin ninguna fila produce un error.
    Dado que un archivo vacío suele indicar que la exportación de origen falló, conviene detener la corrida ahí antes de publicar tableros en blanco.
    """
    ruta = tmp_path / "vacio.csv"
    ruta.write_text(
        "Invoice,StockCode,Quantity,InvoiceDate,Price\n", encoding="utf-8"
    )

    with pytest.raises(ErrorDeIngesta):
        leer_archivo(ruta)


def test_avisa_cuando_faltan_columnas_obligatorias(tmp_path: Path) -> None:
    """
    Comprueba que la ingesta corta cuando el origen cambia y desaparece una columna obligatoria.
    Al respecto, el archivo de prueba solo trae Invoice y Country, de modo que faltan la cantidad, el precio y la fecha, sin las cuales no hay ingreso que calcular.
    """
    origen = pd.DataFrame({"Invoice": ["489434"], "Country": ["UNITED KINGDOM"]})
    ruta = tmp_path / "incompleto.csv"
    origen.to_csv(ruta, index=False)

    with pytest.raises(ErrorDeIngesta, match="columnas obligatorias"):
        leer_archivo(ruta)


def test_verificar_columnas_acepta_una_tabla_completa(ventas_validas: pd.DataFrame) -> None:
    """
    Comprueba que la verificación de columnas guarda silencio cuando la tabla está completa.
    Es decir, sobre un conjunto válido la llamada termina sin levantar ninguna excepción.
    """
    verificar_columnas(ventas_validas)


def test_el_resumen_describe_lo_que_se_leyo(ventas_validas: pd.DataFrame) -> None:
    """
    Comprueba que el resumen de la ingesta trae los conteos con los que se comparan dos corridas seguidas.
    Al respecto, el conjunto válido tiene 5 filas sobre 4 códigos de producto distintos (el 22086 aparece dos veces), y va del 2009-12-01 al 2009-12-02 sin ningún producto nulo.
    """
    resumen = resumir_ingesta(ventas_validas)

    assert resumen["filas_totales"] == 5
    assert resumen["distintos_producto_id"] == 4
    assert resumen["fecha_minima"] == "2009-12-01"
    assert resumen["fecha_maxima"] == "2009-12-02"
    assert resumen["nulos_por_columna"]["producto_id"] == 0
