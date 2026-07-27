"""
Pruebas de la capa de calidad de datos.
Cada regla se prueba por separado con un conjunto donde solo esa regla puede fallar, de manera que un fallo señale sin ambigüedad cuál es la responsable.
Asimismo, se prueba el comportamiento global, en particular las dos condiciones que hacen abortar el pipeline (quedarse sin filas válidas y superar el umbral de rechazo tolerado).
"""

from __future__ import annotations

import pandas as pd
import pytest

from trabajos.configuracion import ConfiguracionPipeline
from trabajos.validaciones import (
    ErrorDeCalidad,
    construir_reglas,
    validar,
    verificar_agregado,
)


def test_un_conjunto_limpio_no_pierde_ninguna_fila(
    ventas_validas: pd.DataFrame, configuracion_temporal: ConfiguracionPipeline
) -> None:
    """
    Comprueba que un conjunto limpio atraviesa la validación sin perder ninguna fila.
    Al respecto, las 5 filas de entrada quedan como 5 válidas, 0 rechazadas y un porcentaje de rechazo de 0.0, con la cuarentena vacía.
    """
    resultado = validar(ventas_validas, configuracion_temporal)

    assert resultado.filas_validas == 5
    assert resultado.filas_rechazadas == 0
    assert resultado.porcentaje_rechazo == 0.0
    assert resultado.rechazados.empty


def test_cada_regla_atrapa_exactamente_su_caso(
    ventas_con_problemas: pd.DataFrame, configuracion_temporal: ConfiguracionPipeline
) -> None:
    """
    Comprueba que cada regla atrapa exactamente el caso que le corresponde y ninguno más.
    Al respecto, de las 10 filas de entrada quedan 5 válidas y 5 rechazadas, con un rechazo por cada una de estas reglas: Columnas obligatorias sin nulos, fecha dentro de rango, cantidad mínima, precio en rango y sin duplicados exactos.
    """
    resultado = validar(ventas_con_problemas, configuracion_temporal)

    assert resultado.filas_entrada == 10
    assert resultado.filas_validas == 5
    assert resultado.filas_rechazadas == 5

    conteo = resultado.conteo_por_regla
    assert conteo["columnas_obligatorias_sin_nulos"] == 1
    assert conteo["fecha_dentro_de_rango"] == 1
    assert conteo["cantidad_minima"] == 1
    assert conteo["precio_en_rango"] == 1
    assert conteo["sin_duplicados_exactos"] == 1


def test_las_filas_rechazadas_llevan_su_motivo(
    ventas_con_problemas: pd.DataFrame, configuracion_temporal: ConfiguracionPipeline
) -> None:
    """
    Comprueba que toda fila rechazada llega a la cuarentena acompañada de su motivo.
    De ese modo, quien revise el archivo de descartes entiende por qué salió cada registro sin tener que reconstruir la validación a mano.
    """
    resultado = validar(ventas_con_problemas, configuracion_temporal)

    assert "motivo_rechazo" in resultado.rechazados.columns
    assert resultado.rechazados["motivo_rechazo"].notna().all()

    motivos = set(resultado.rechazados["motivo_rechazo"])
    assert "cantidad_minima" in motivos
    assert "precio_en_rango" in motivos


def test_una_fila_recibe_un_solo_motivo(configuracion_temporal: ConfiguracionPipeline) -> None:
    """
    Comprueba que una fila que incumple varias reglas recibe un solo motivo, el de la primera regla del catálogo que la atrapa.
    Al respecto, la fila de prueba tiene cantidad negativa y precio fuera de rango al mismo tiempo, de modo que podría contarse dos veces.
    En consecuencia, la suma de los conteos por regla coincide con el total de filas rechazadas, condición que hace confiable el tablero de calidad.
    """
    fila_muy_mala = pd.DataFrame(
        {
            "factura": ["489999"],
            "producto_id": ["22086"],
            "descripcion": ["INCUMPLE VARIAS REGLAS"],
            # La fila siguiente lleva a la vez una cantidad negativa y un precio fuera de rango, que es justamente la combinación que se quiere ejercitar.
            "cantidad": pd.array([-5], dtype="Int64"),
            "fecha_hora": pd.to_datetime(["2010-05-05 10:00:00"]),
            "fecha": [pd.Timestamp("2010-05-05").date()],
            "precio_unitario": [99_999.0],
            "cliente_id": pd.array([13085], dtype="Int64"),
            "pais": ["UNITED KINGDOM"],
        }
    )
    conjunto = pd.concat(
        [fila_muy_mala.assign(cantidad=pd.array([5], dtype="Int64"), precio_unitario=[2.0])]
        * 9
        + [fila_muy_mala],
        ignore_index=True,
    )

    resultado = validar(conjunto, configuracion_temporal)

    assert sum(resultado.conteo_por_regla.values()) == resultado.filas_rechazadas


def test_falla_cuando_se_supera_el_umbral_de_rechazo(
    ventas_validas: pd.DataFrame, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Comprueba que superar el umbral de rechazo detiene la corrida antes de publicar nada.
    Al respecto, se agregan 3 filas con cantidad cero sobre las 5 válidas, lo que da 3 rechazos sobre 8 filas, es decir, un 37.5 por ciento frente a un máximo tolerado del 5.0 por ciento.
    """
    monkeypatch.setenv("PORCENTAJE_RECHAZO_MAXIMO", "5.0")
    configuracion = ConfiguracionPipeline()

    # La cuenta del rechazo es 3 entre 8, que da 37.5 por ciento y queda muy por encima del 5.0 configurado.
    malas = ventas_validas.head(3).copy()
    malas["cantidad"] = pd.array([0, 0, 0], dtype="Int64")
    malas["factura"] = ["X1", "X2", "X3"]
    conjunto = pd.concat([ventas_validas, malas], ignore_index=True)

    with pytest.raises(ErrorDeCalidad, match="por encima del máximo tolerado"):
        validar(conjunto, configuracion)


def test_falla_cuando_no_queda_ninguna_fila_valida(
    ventas_validas: pd.DataFrame, configuracion_temporal: ConfiguracionPipeline
) -> None:
    """
    Comprueba que quedarse sin ninguna fila válida corta la corrida con un mensaje explícito.
    Al respecto, se pone la cantidad en menos uno en todas las filas, con lo cual la regla de cantidad mínima las rechaza a todas.
    Puesto que seguir adelante produciría tablas vacías en el almacén, resulta preferible detenerse y decirlo.
    """
    todas_malas = ventas_validas.copy()
    todas_malas["cantidad"] = pd.array([-1] * len(todas_malas), dtype="Int64")

    with pytest.raises(ErrorDeCalidad, match="Ninguna fila superó"):
        validar(todas_malas, configuracion_temporal)


def test_los_umbrales_de_precio_se_leen_de_la_configuracion(
    ventas_validas: pd.DataFrame, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Comprueba que los umbrales de precio se leen de la configuración y no están fijos en el código.
    Al respecto, con el precio máximo puesto en 5.0 quedan afuera la fila de 6.00 y la de 10.00, de manera que se rechazan 2 filas y sobreviven 3 de las 5.
    """
    monkeypatch.setenv("PRECIO_MAXIMO", "5.0")
    monkeypatch.setenv("PORCENTAJE_RECHAZO_MAXIMO", "90.0")
    configuracion = ConfiguracionPipeline()

    resultado = validar(ventas_validas, configuracion)

    # Con el tope en 5.0 quedan afuera las dos filas cuyo precio unitario es 6.00 y 10.00.
    assert resultado.conteo_por_regla["precio_en_rango"] == 2
    assert resultado.filas_validas == 3


def test_el_catalogo_de_reglas_describe_cada_una(
    configuracion_temporal: ConfiguracionPipeline,
) -> None:
    """
    Comprueba que el catálogo aporta las 6 reglas y que cada una trae nombre, descripción y una función que detecta los incumplimientos.
    Al respecto, el nombre y la descripción son lo que se muestra en el reporte de calidad, motivo por el cual una regla sin ellos dejaría al lector sin saber qué se descartó.
    """
    reglas = construir_reglas(configuracion_temporal)

    assert len(reglas) == 6
    for regla in reglas:
        assert regla.nombre
        assert regla.descripcion
        assert callable(regla.detectar)


def test_el_agregado_correcto_pasa_la_verificacion_final() -> None:
    """
    Comprueba que un agregado bien formado atraviesa la verificación final sin observaciones.
    Al respecto, las 2 filas tienen fechas distintas para el mismo producto, de modo que no hay claves duplicadas ni problemas que reportar.
    """
    agregado = pd.DataFrame(
        {
            "fecha": [pd.Timestamp("2009-12-01").date(), pd.Timestamp("2009-12-02").date()],
            "producto_id": ["22086", "22086"],
            "ingreso_total": [75.0, 5.0],
        }
    )

    detalle = verificar_agregado(agregado)

    assert detalle["filas_agregado"] == 2
    assert detalle["claves_duplicadas"] == 0
    assert detalle["problemas"] == []


def test_la_verificacion_final_detecta_claves_repetidas() -> None:
    """
    Comprueba que la verificación final detecta una clave repetida en el agregado.
    Al respecto, las dos filas comparten fecha y producto, situación que solo puede originarse en una agrupación rota.
    En consecuencia, el corte ocurre antes de publicar, ya que un agregado con la clave duplicada haría que los tableros contaran dos veces el mismo ingreso.
    """
    agregado = pd.DataFrame(
        {
            "fecha": [pd.Timestamp("2009-12-01").date()] * 2,
            "producto_id": ["22086", "22086"],
            "ingreso_total": [75.0, 25.0],
        }
    )

    with pytest.raises(ErrorDeCalidad, match="se repite"):
        verificar_agregado(agregado)


def test_la_verificacion_final_detecta_ingresos_negativos() -> None:
    """
    Comprueba que la verificación final rechaza un agregado con ingreso negativo.
    Puesto que las devoluciones se descartan durante la validación, un importe negativo en la salida delata un error de cálculo y no un dato legítimo.
    """
    agregado = pd.DataFrame(
        {
            "fecha": [pd.Timestamp("2009-12-01").date()],
            "producto_id": ["22086"],
            "ingreso_total": [-10.0],
        }
    )

    with pytest.raises(ErrorDeCalidad, match="negativo"):
        verificar_agregado(agregado)


def test_la_verificacion_final_rechaza_un_agregado_vacio() -> None:
    """
    Comprueba que la verificación final rechaza un agregado sin ninguna fila.
    Al respecto, publicar una tabla vacía dejaría los tableros en blanco sin que nadie recibiera aviso, cosa que se lee como un problema de la herramienta y no del pipeline.
    """
    with pytest.raises(ErrorDeCalidad):
        verificar_agregado(pd.DataFrame(columns=["fecha", "producto_id", "ingreso_total"]))
