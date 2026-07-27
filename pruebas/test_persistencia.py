"""
Pruebas de la escritura de resultados en disco.
Interesa comprobar tres cosas: Lo escrito se puede volver a leer sin perder información, reejecutar el pipeline no duplica datos y los errores se reportan con una excepción propia.
Cabe señalar que esa excepción propia importa porque un rastro de pila de la biblioteca de Parquet no le dice a nadie qué ruta falló.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from trabajos.persistencia import (
    ErrorDePersistencia,
    guardar_csv,
    guardar_cuarentena,
    guardar_parquet,
    guardar_reporte,
    leer_parquet,
)


def test_lo_escrito_en_parquet_se_recupera_igual(tmp_path: Path) -> None:
    """
    Comprueba que el ciclo de escribir y volver a leer conserva las filas y los valores.
    Al respecto, se guardan dos productos con 75.00 y 30.00 de ingreso, de manera que la suma recuperada tiene que dar 105.00.
    """
    datos = pd.DataFrame(
        {"producto_id": ["22086", "85048"], "ingreso_total": [75.0, 30.0]}
    )
    ruta = tmp_path / "resultado"

    guardar_parquet(datos, ruta)
    recuperado = leer_parquet(ruta)

    assert len(recuperado) == 2
    assert round(recuperado["ingreso_total"].sum(), 2) == 105.0
    assert set(recuperado["producto_id"]) == {"22086", "85048"}


def test_el_particionado_genera_subcarpetas(tmp_path: Path) -> None:
    """
    Comprueba que particionar por año y mes crea la estructura de directorios esperada.
    Al respecto, las dos filas corresponden a diciembre de 2009 y a enero de 2010, motivo por el cual aparecen las rutas anio=2009/mes=12 y anio=2010/mes=1.
    Adicionalmente, la lectura del conjunto particionado devuelve las 2 filas, lo que confirma que las columnas de partición no se pierden.
    """
    datos = pd.DataFrame(
        {
            "producto_id": ["22086", "85048"],
            "ingreso_total": [75.0, 30.0],
            "anio": [2009, 2010],
            "mes": [12, 1],
        }
    )
    ruta = tmp_path / "particionado"

    guardar_parquet(datos, ruta, columnas_particion=["anio", "mes"])

    assert (ruta / "anio=2009" / "mes=12").exists()
    assert (ruta / "anio=2010" / "mes=1").exists()
    assert len(leer_parquet(ruta)) == 2


def test_reescribir_no_acumula_datos_de_corridas_anteriores(tmp_path: Path) -> None:
    """
    Comprueba que reescribir una ruta reemplaza el contenido en lugar de acumularlo.
    Al respecto, primero se guardan 3 filas y después una sola, de modo que la lectura posterior tiene que devolver esa única fila con valor 9.
    De ese modo, la escritura resulta idempotente y una tarea se puede reintentar sin dejar datos duplicados.
    """
    ruta = tmp_path / "resultado"

    guardar_parquet(pd.DataFrame({"valor": [1, 2, 3]}), ruta)
    guardar_parquet(pd.DataFrame({"valor": [9]}), ruta)

    recuperado = leer_parquet(ruta)
    assert len(recuperado) == 1
    assert recuperado["valor"].iloc[0] == 9


def test_las_fechas_sobreviven_al_viaje_a_parquet(tmp_path: Path) -> None:
    """
    Comprueba que las fechas sobreviven al viaje de ida y vuelta a Parquet.
    Al respecto, el tipo date de Python se guarda como marca de tiempo y se recupera como tal, conservando el 2009-12-01 como fecha mínima.
    Conviene precisar que sin esta comprobación una conversión silenciosa a texto pasaría inadvertida hasta que alguien intentara filtrar por rango de fechas.
    """
    datos = pd.DataFrame(
        {
            "fecha": [pd.Timestamp("2009-12-01").date(), pd.Timestamp("2009-12-02").date()],
            "ingreso_total": [105.0, 85.0],
        }
    )
    ruta = tmp_path / "con_fechas"

    guardar_parquet(datos, ruta)
    recuperado = leer_parquet(ruta)

    assert pd.api.types.is_datetime64_any_dtype(recuperado["fecha"])
    assert str(recuperado["fecha"].min().date()) == "2009-12-01"


def test_el_csv_se_escribe_con_acentos_correctos(tmp_path: Path) -> None:
    """
    Comprueba que el CSV se escribe en UTF-8 y conserva los acentos.
    Al respecto, "ARTÍCULO DE DECORACIÓN" tiene que leerse igual desde el archivo, ya que una codificación equivocada convertiría los nombres de producto en símbolos ilegibles al abrirlos en una planilla.
    """
    datos = pd.DataFrame({"descripcion": ["ARTÍCULO DE DECORACIÓN"], "ingreso_total": [10.0]})
    ruta = tmp_path / "salida.csv"

    guardar_csv(datos, ruta)

    contenido = ruta.read_text(encoding="utf-8")
    assert "ARTÍCULO DE DECORACIÓN" in contenido


def test_el_reporte_queda_como_json_valido(tmp_path: Path) -> None:
    """
    Comprueba que el reporte de la corrida queda como JSON válido y se puede volver a leer con cualquier herramienta.
    Al respecto, el contenido incluye una marca de tiempo de pandas, tipo que no es serializable de fábrica, motivo por el cual la escritura tiene que convertirlo antes de guardarlo.
    """
    contenido = {
        "identificador_corrida": "20091201-100000",
        "filas": 1000,
        "fecha": pd.Timestamp("2009-12-01"),
    }
    ruta = tmp_path / "reporte.json"

    guardar_reporte(contenido, ruta)
    recuperado = json.loads(ruta.read_text(encoding="utf-8"))

    assert recuperado["filas"] == 1000
    assert recuperado["identificador_corrida"] == "20091201-100000"


def test_la_cuarentena_guarda_las_filas_con_su_motivo(tmp_path: Path) -> None:
    """
    Comprueba que la cuarentena guarda las filas rechazadas junto con el motivo de cada descarte.
    Al respecto, el archivo toma el identificador de la corrida en su nombre (rechazados_20091201-100000.csv), de modo que se puede saber a qué ejecución pertenece sin abrirlo.
    """
    rechazados = pd.DataFrame(
        {
            "producto_id": ["22086", "85048"],
            "cantidad": [-5, 3],
            "motivo_rechazo": ["cantidad_minima", "precio_en_rango"],
        }
    )

    ruta = guardar_cuarentena(rechazados, tmp_path, "20091201-100000")

    assert ruta is not None
    assert ruta.name == "rechazados_20091201-100000.csv"
    recuperado = pd.read_csv(ruta)
    assert len(recuperado) == 2
    assert "motivo_rechazo" in recuperado.columns


def test_sin_rechazos_no_se_genera_archivo_de_cuarentena(tmp_path: Path) -> None:
    """
    Comprueba que sin filas rechazadas no se genera ningún archivo de cuarentena.
    Puesto que una corrida limpia es lo normal, dejar un archivo vacío por cada una llenaría la carpeta de residuos que después hay que limpiar a mano.
    """
    resultado = guardar_cuarentena(pd.DataFrame(), tmp_path, "20091201-100000")

    assert resultado is None
    assert list(tmp_path.glob("rechazados_*.csv")) == []


def test_leer_un_parquet_inexistente_avisa_con_claridad(tmp_path: Path) -> None:
    """
    Comprueba que leer un Parquet inexistente levanta el error propio del módulo indicando qué ruta falló.
    De ese modo, quien revise el registro identifica la ruta equivocada en la primera línea del mensaje.
    """
    with pytest.raises(ErrorDePersistencia, match="No existe el Parquet"):
        leer_parquet(tmp_path / "no_esta")
