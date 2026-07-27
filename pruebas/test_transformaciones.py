"""
Pruebas de las transformaciones de negocio.
Cabe señalar que se trata de las pruebas más importantes del proyecto, puesto que acá vive la lógica que produce los números que después mira la gente.
Al respecto, los valores esperados están calculados a mano en los comentarios, de manera que quien lea la prueba pueda verificar la cuenta sin ejecutar nada.
"""

from __future__ import annotations

import pandas as pd
import pytest

from trabajos.transformaciones import (
    agregar_por_producto_y_fecha,
    agregar_resumen_diario,
    calcular_ingreso_total,
    enriquecer_con_calendario,
    ranking_de_productos,
)


def test_el_ingreso_de_cada_linea_es_cantidad_por_precio(ventas_validas: pd.DataFrame) -> None:
    """
    Comprueba que el ingreso de cada línea es la cantidad multiplicada por el precio unitario.
    Al respecto, las cuentas de las cinco filas son 10 por 2.50 igual a 25.00, 5 por 6.00 igual a 30.00, 20 por 2.50 igual a 50.00, 4 por 1.25 igual a 5.00 y 8 por 10.00 igual a 80.00.
    """
    resultado = calcular_ingreso_total(ventas_validas)

    assert list(resultado["ingreso_total"]) == [25.0, 30.0, 50.0, 5.0, 80.0]


def test_el_ingreso_se_redondea_a_dos_decimales() -> None:
    """
    Comprueba que el ingreso se redondea a dos decimales, que es la precisión de la moneda.
    De lo contrario, los residuos de la multiplicación se acumularían al sumar millones de líneas y los totales dejarían de cerrar contra la contabilidad.
    """
    datos = pd.DataFrame(
        {"cantidad": pd.array([3], dtype="Int64"), "precio_unitario": [1.9999]}
    )

    resultado = calcular_ingreso_total(datos)

    # La cuenta es 3 por 1.9999, que da 5.9997 y redondeado a dos decimales queda en 6.00.
    assert resultado["ingreso_total"].iloc[0] == 6.0


def test_calcular_ingreso_no_modifica_la_tabla_original(ventas_validas: pd.DataFrame) -> None:
    """
    Comprueba que el cálculo del ingreso deja intacta la tabla que recibe.
    Es decir, la función devuelve una copia con la columna nueva y no modifica la entrada, condición que permite encadenar transformaciones sin efectos ocultos entre ellas.
    """
    columnas_antes = list(ventas_validas.columns)

    calcular_ingreso_total(ventas_validas)

    assert list(ventas_validas.columns) == columnas_antes
    assert "ingreso_total" not in ventas_validas.columns


def test_avisa_si_faltan_las_columnas_para_el_calculo() -> None:
    """
    Comprueba que la función avisa cuando faltan las columnas necesarias para el cálculo.
    Dado que sin cantidad y sin precio no hay ingreso posible, el error explícito resulta preferible a una columna de nulos que nadie note hasta ver el tablero en cero.
    """
    with pytest.raises(KeyError, match="ingreso total"):
        calcular_ingreso_total(pd.DataFrame({"producto_id": ["22086"]}))


def test_el_agregado_suma_las_lineas_de_la_misma_clave(ventas_validas: pd.DataFrame) -> None:
    """
    Comprueba que dos líneas del mismo producto y del mismo día se combinan en una sola fila del agregado.
    Al respecto, el producto 22086 vendió 25.00 y 50.00 el primero de diciembre, motivo por el cual su fila tiene que valer 75.00.
    Del mismo modo, las unidades suman 10 más 20 igual a 30, sobre 2 líneas de factura repartidas en 2 facturas distintas.
    """
    detalle = calcular_ingreso_total(ventas_validas)
    agregado = agregar_por_producto_y_fecha(detalle)

    fila = agregado[
        (agregado["producto_id"] == "22086")
        & (agregado["fecha"] == pd.Timestamp("2009-12-01").date())
    ]

    assert len(fila) == 1
    assert fila["ingreso_total"].iloc[0] == 75.0
    assert fila["unidades_vendidas"].iloc[0] == 30
    assert fila["lineas_de_factura"].iloc[0] == 2
    assert fila["facturas_distintas"].iloc[0] == 2


def test_la_clave_del_agregado_es_unica(ventas_validas: pd.DataFrame) -> None:
    """
    Comprueba que la pareja de fecha y producto identifica una sola fila del agregado.
    Al respecto, las 5 líneas de entrada se reducen a 4 filas, ya que las dos del producto 22086 del primero de diciembre se funden en una.
    Conviene precisar que esta unicidad es la que permite cargar la tabla en el almacén con una clave primaria y detectar cualquier duplicación antes de publicar.
    """
    detalle = calcular_ingreso_total(ventas_validas)
    agregado = agregar_por_producto_y_fecha(detalle)

    assert not agregado.duplicated(subset=["fecha", "producto_id"]).any()
    assert len(agregado) == 4


def test_la_agregacion_conserva_el_ingreso_total(ventas_validas: pd.DataFrame) -> None:
    """
    Comprueba que la agregación no crea ni pierde dinero.
    Al respecto, la suma del detalle y la del agregado tienen que coincidir hasta el último centavo, invariante que constituye la más importante de todo el pipeline.
    La cuenta es 25.00 más 30.00 más 50.00 más 5.00 más 80.00, que da 190.00 por ambos caminos.
    """
    detalle = calcular_ingreso_total(ventas_validas)
    agregado = agregar_por_producto_y_fecha(detalle)

    assert round(detalle["ingreso_total"].sum(), 2) == round(agregado["ingreso_total"].sum(), 2)
    assert round(agregado["ingreso_total"].sum(), 2) == 190.0


def test_el_agregado_queda_ordenado_por_fecha(ventas_validas: pd.DataFrame) -> None:
    """
    Comprueba que el agregado sale ordenado de manera ascendente por fecha.
    De ese modo, quien abra el archivo lee la serie en orden cronológico y las herramientas de graficado no tienen que reordenar nada.
    """
    detalle = calcular_ingreso_total(ventas_validas)
    agregado = agregar_por_producto_y_fecha(detalle)

    fechas = list(agregado["fecha"])
    assert fechas == sorted(fechas)


def test_el_agregado_toma_la_descripcion_mas_frecuente() -> None:
    """
    Comprueba que cuando un mismo código de producto trae descripciones distintas se conserva la mayoritaria.
    Al respecto, el código 22086 aparece dos veces como "NOMBRE BUENO" y una como "nombre con error", de modo que el agregado se queda con la primera.
    Dicho de otro modo, la escritura más repetida se toma como la correcta, criterio que evita que una carga con un texto mal tipeado cambie el nombre del producto en los tableros.
    """
    datos = pd.DataFrame(
        {
            "factura": ["1", "2", "3"],
            "producto_id": ["22086", "22086", "22086"],
            "descripcion": ["NOMBRE BUENO", "NOMBRE BUENO", "nombre con error"],
            "cantidad": pd.array([1, 1, 1], dtype="Int64"),
            "fecha": [pd.Timestamp("2009-12-01").date()] * 3,
            "precio_unitario": [1.0, 1.0, 1.0],
            "ingreso_total": [1.0, 1.0, 1.0],
        }
    )

    agregado = agregar_por_producto_y_fecha(datos)

    assert agregado["descripcion_producto"].iloc[0] == "NOMBRE BUENO"


def test_el_resumen_diario_tiene_una_fila_por_dia(ventas_validas: pd.DataFrame) -> None:
    """
    Comprueba que el resumen diario colapsa los productos y deja una sola fila por día.
    Al respecto, el conjunto cubre dos fechas, motivo por el cual el resumen tiene 2 filas y el primero de diciembre acumula 2 productos distintos.
    """
    detalle = calcular_ingreso_total(ventas_validas)
    agregado = agregar_por_producto_y_fecha(detalle)
    resumen = agregar_resumen_diario(agregado)

    assert len(resumen) == 2
    # El primero de diciembre facturó 75.00 del producto 22086 más 30.00 del 85048, que da 105.00.
    assert resumen["ingreso_total"].iloc[0] == 105.0
    # El dos de diciembre facturó 5.00 del producto 21232 más 80.00 del 84879, que da 85.00.
    assert resumen["ingreso_total"].iloc[1] == 85.0
    assert resumen["productos_distintos"].iloc[0] == 2


def test_el_resumen_diario_soporta_una_entrada_vacia() -> None:
    """
    Comprueba que el resumen diario tolera una tabla de entrada vacía.
    Al respecto, devuelve una tabla vacía pero con las columnas esperadas, de modo que quien consuma el resultado no tenga que distinguir ese caso de los demás.
    """
    resumen = agregar_resumen_diario(pd.DataFrame())

    assert resumen.empty
    assert "ingreso_total" in resumen.columns


def test_el_ranking_ordena_de_mayor_a_menor(ventas_validas: pd.DataFrame) -> None:
    """
    Comprueba que el ranking ordena los productos de mayor a menor facturación.
    Al respecto, los totales del período son 80.00 para el 84879, 75.00 para el 22086, 30.00 para el 85048 y 5.00 para el 21232.
    En consecuencia, el 84879 ocupa la posición 1 con sus 80.00 y la columna de ingresos queda en orden descendente.
    """
    detalle = calcular_ingreso_total(ventas_validas)
    agregado = agregar_por_producto_y_fecha(detalle)
    ranking = ranking_de_productos(agregado, cantidad=10)

    assert ranking["producto_id"].iloc[0] == "84879"
    assert ranking["ingreso_total"].iloc[0] == 80.0
    assert ranking["posicion"].iloc[0] == 1
    assert list(ranking["ingreso_total"]) == sorted(ranking["ingreso_total"], reverse=True)


def test_el_ranking_respeta_el_limite_pedido(ventas_validas: pd.DataFrame) -> None:
    """
    Comprueba que el parámetro de cantidad recorta el ranking.
    Al respecto, hay 4 productos en el período y con el límite en 2 el resultado trae únicamente los dos primeros.
    """
    detalle = calcular_ingreso_total(ventas_validas)
    agregado = agregar_por_producto_y_fecha(detalle)

    assert len(ranking_de_productos(agregado, cantidad=2)) == 2


def test_las_participaciones_del_ranking_suman_cien(ventas_validas: pd.DataFrame) -> None:
    """
    Comprueba que la participación acumulada del ranking cierra en cien cuando se incluyen todos los productos.
    Al respecto, los 190.00 del período se reparten en 80.00, 75.00, 30.00 y 5.00, de manera que la última fila tiene que llegar al 100.0 por ciento.
    Puesto que esa columna es la que sostiene el análisis de concentración, un cierre distinto de cien delataría un error en el denominador.
    """
    detalle = calcular_ingreso_total(ventas_validas)
    agregado = agregar_por_producto_y_fecha(detalle)
    ranking = ranking_de_productos(agregado, cantidad=100)

    assert round(ranking["participacion_acumulada"].iloc[-1], 1) == 100.0


def test_el_calendario_deriva_los_atributos_de_la_fecha(ventas_validas: pd.DataFrame) -> None:
    """
    Comprueba que el enriquecimiento con calendario deriva de la fecha el año, el mes, el período y el día de la semana.
    Al respecto, la primera fila es del 2009-12-01, motivo por el cual su año es 2009, su mes es 12 y su período es "2009-12".
    """
    resultado = enriquecer_con_calendario(ventas_validas)

    assert resultado["anio"].iloc[0] == 2009
    assert resultado["mes"].iloc[0] == 12
    assert resultado["anio_mes"].iloc[0] == "2009-12"
    # El primero de diciembre de 2009 cayó en martes, que corresponde al día 1 en una numeración que empieza en cero el lunes.
    assert resultado["dia_semana"].iloc[0] == 1
    assert not resultado["es_fin_de_semana"].iloc[0]


def test_el_calendario_marca_bien_los_fines_de_semana() -> None:
    """
    Comprueba que la marca de fin de semana señala el sábado y el domingo, y deja sin marcar los días hábiles.
    Al respecto, las tres fechas de prueba son el sábado 5, el domingo 6 y el lunes 7 de diciembre de 2009, de manera que el resultado esperado es verdadero, verdadero y falso.
    """
    datos = pd.DataFrame(
        {
            "fecha": [
                pd.Timestamp("2009-12-05").date(),
                pd.Timestamp("2009-12-06").date(),
                pd.Timestamp("2009-12-07").date(),
            ]
        }
    )

    resultado = enriquecer_con_calendario(datos)

    assert list(resultado["es_fin_de_semana"]) == [True, True, False]


def test_el_calendario_necesita_la_columna_fecha() -> None:
    """
    Comprueba que el enriquecimiento avisa cuando la tabla no trae la columna de fecha.
    Puesto que todos los atributos de calendario se derivan de ella, sin esa columna no hay nada que calcular y conviene decirlo con un error claro.
    """
    with pytest.raises(KeyError, match="fecha"):
        enriquecer_con_calendario(pd.DataFrame({"producto_id": ["22086"]}))
