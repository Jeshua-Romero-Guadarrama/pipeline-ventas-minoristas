"""
Transformaciones de negocio del pipeline de ventas.
Al respecto, este módulo constituye el núcleo del proyecto, dado que todas sus funciones son puras, es decir, reciben una tabla y devuelven otra sin tocar disco ni variables globales.
Dicha decisión no es casual, puesto que permite probar cada regla de negocio con tablas de tres filas armadas a mano y sin levantar ninguna infraestructura.
El cálculo central es el ingreso total de cada línea de factura, que resulta de multiplicar la cantidad por el precio unitario (una línea de 3 unidades a 12.99 arroja un ingreso de 38.97).
A partir de ese valor se construyen las agregaciones que consumen los tableros.
"""

from __future__ import annotations

import pandas as pd

from trabajos.registro import obtener_registrador

registrador = obtener_registrador(__name__)


def calcular_ingreso_total(datos: pd.DataFrame, copiar: bool = True) -> pd.DataFrame:
    """
    Agrega la columna ingreso_total a nivel de línea de factura, multiplicando la cantidad por el precio unitario.
    Por ejemplo, una línea de 3 unidades a 12.99 queda con un ingreso de 38.97.
    El redondeo a dos decimales se aplica en este punto y no al final, en razón de que el importe de una línea de factura es un valor monetario real, de manera que sumar importes ya redondeados reproduce el total que muestra el sistema contable de origen (que es justamente contra lo que se compara).
    Recibe una tabla con las columnas cantidad y precio_unitario, además del indicador copiar.
    Siempre que copiar valga True, la función es pura y deja la entrada intacta, comportamiento que esperan las pruebas y cualquier uso desde un cuaderno de análisis.
    En cambio, el orquestador lo pone en False porque es dueño de la tabla y no la necesita después, con lo que evita duplicar en memoria un millón de filas para no obtener nada distinto.
    Devuelve la tabla con la columna ingreso_total agregada.
    Lanza KeyError en caso de que falte alguna de las dos columnas necesarias.
    """
    faltantes = [c for c in ("cantidad", "precio_unitario") if c not in datos.columns]
    if faltantes:
        raise KeyError(
            f"Para calcular el ingreso total hacen falta las columnas {faltantes}. "
            "Conviene revisar el paso de ingesta, dado que el ingreso de cada línea "
            "se obtiene multiplicando cantidad por precio_unitario."
        )

    resultado = datos.copy() if copiar else datos
    cantidad = resultado["cantidad"].astype("float64")
    precio = resultado["precio_unitario"].astype("float64")
    resultado["ingreso_total"] = (cantidad * precio).round(2)

    registrador.info(
        "Ingreso total calculado a nivel de línea",
        extra={
            "filas": int(len(resultado)),
            "ingreso_acumulado": float(resultado["ingreso_total"].sum().round(2)),
        },
    )
    return resultado


def agregar_por_producto_y_fecha(datos: pd.DataFrame) -> pd.DataFrame:
    """
    Construye el agregado principal que pide el enunciado del proyecto, agrupando por fecha y producto.
    Junto al ingreso total sumado se calculan métricas de apoyo que ayudan a interpretarlo.
    Al respecto, las unidades vendidas y la cantidad de facturas distintas permiten distinguir un producto caro que se vende poco de uno barato que se vende mucho, algo que el ingreso por sí solo no revela.
    Por ejemplo, un producto con 1000.00 de ingreso en 2 unidades y otro con 1000.00 en 500 unidades comparten la misma facturación, aunque describen negocios muy distintos.
    Recibe la tabla de detalle con la columna ingreso_total ya calculada.
    Devuelve una tabla con una fila por combinación de fecha y producto, ordenada por fecha ascendente y, dentro de cada fecha, por ingreso descendente.
    Lanza KeyError siempre que falte alguna de las columnas necesarias para agrupar.
    """
    requeridas = ("fecha", "producto_id", "ingreso_total", "cantidad")
    faltantes = [c for c in requeridas if c not in datos.columns]
    if faltantes:
        raise KeyError(
            f"Para agregar por producto y fecha hacen falta las columnas {faltantes}. "
            "Conviene ejecutar antes calcular_ingreso_total, que es el paso que aporta la columna ingreso_total."
        )

    agrupado = datos.groupby(["fecha", "producto_id"], dropna=False, observed=True)

    agregado = agrupado.agg(
        ingreso_total=("ingreso_total", "sum"),
        unidades_vendidas=("cantidad", "sum"),
        lineas_de_factura=("ingreso_total", "size"),
        precio_unitario_promedio=("precio_unitario", "mean"),
    ).reset_index()

    if "factura" in datos.columns:
        facturas_distintas = (
            agrupado["factura"].nunique().reset_index(name="facturas_distintas")
        )
        agregado = agregado.merge(facturas_distintas, on=["fecha", "producto_id"], how="left")

    # La descripción se toma como la más frecuente, puesto que el mismo código de producto aparece con textos ligeramente distintos según quién cargó cada línea.
    # Por ejemplo, el producto 85123A figura como "TAZA BLANCA" en la mayoría de sus líneas y como "taza blanca" en unas pocas, de modo que la moda conserva la forma dominante.
    if "descripcion" in datos.columns:
        descripciones = (
            datos.dropna(subset=["descripcion"])
            .groupby("producto_id", observed=True)["descripcion"]
            .agg(lambda serie: serie.mode().iloc[0] if not serie.mode().empty else pd.NA)
            .reset_index()
            .rename(columns={"descripcion": "descripcion_producto"})
        )
        agregado = agregado.merge(descripciones, on="producto_id", how="left")

    agregado["ingreso_total"] = agregado["ingreso_total"].round(2)
    agregado["precio_unitario_promedio"] = agregado["precio_unitario_promedio"].round(4)
    agregado["unidades_vendidas"] = agregado["unidades_vendidas"].astype("int64")

    agregado = agregado.sort_values(
        by=["fecha", "ingreso_total"], ascending=[True, False]
    ).reset_index(drop=True)

    registrador.info(
        "Agregado por producto y fecha construido",
        extra={
            "filas_agregado": int(len(agregado)),
            "productos_distintos": int(agregado["producto_id"].nunique()),
            "fechas_distintas": int(agregado["fecha"].nunique()),
            "ingreso_total": float(agregado["ingreso_total"].sum().round(2)),
        },
    )
    return agregado


def agregar_resumen_diario(agregado: pd.DataFrame) -> pd.DataFrame:
    """
    Colapsa el agregado por producto a un resumen de una fila por día.
    Sirve para el panel de tendencia del tablero, donde interesa la evolución del ingreso y no el detalle producto por producto.
    Recibe la tabla que devuelve agregar_por_producto_y_fecha.
    Devuelve una tabla con una fila por fecha y sus métricas del día, incluido el ingreso promedio por producto (un día con 900.00 de ingreso repartido entre 3 productos arroja un promedio de 300.00).
    En caso de que el agregado llegue vacío, el resultado es una tabla igualmente vacía pero con las columnas esperadas, de modo que quien la consume no necesita distinguir ese caso.
    """
    if agregado.empty:
        return pd.DataFrame(
            columns=[
                "fecha",
                "ingreso_total",
                "unidades_vendidas",
                "productos_distintos",
                "ingreso_promedio_por_producto",
            ]
        )

    resumen = (
        agregado.groupby("fecha", observed=True)
        .agg(
            ingreso_total=("ingreso_total", "sum"),
            unidades_vendidas=("unidades_vendidas", "sum"),
            productos_distintos=("producto_id", "nunique"),
        )
        .reset_index()
    )

    resumen["ingreso_total"] = resumen["ingreso_total"].round(2)
    resumen["ingreso_promedio_por_producto"] = (
        resumen["ingreso_total"] / resumen["productos_distintos"]
    ).round(2)
    resumen = resumen.sort_values("fecha").reset_index(drop=True)

    registrador.info("Resumen diario construido", extra={"dias": int(len(resumen))})
    return resumen


def ranking_de_productos(agregado: pd.DataFrame, cantidad: int = 20) -> pd.DataFrame:
    """
    Devuelve los productos que más facturaron en todo el período.
    Recibe la tabla que devuelve agregar_por_producto_y_fecha y el número de productos que debe incluir el ranking.
    Devuelve una tabla ordenada de mayor a menor ingreso, con la participación de cada producto sobre el total y su participación acumulada.
    Cabe señalar que la participación acumulada permite leer la concentración de un vistazo (si el quinto renglón ya alcanza 80.0, esos cinco productos explican cuatro quintos de la facturación).
    En caso de que el ingreso del período sea cero, las columnas de participación no se agregan, en razón de que dividir entre cero no arrojaría ningún porcentaje interpretable.
    """
    if agregado.empty:
        return pd.DataFrame(
            columns=["producto_id", "ingreso_total", "participacion_porcentual"]
        )

    columnas_agregacion: dict[str, tuple[str, str]] = {
        "ingreso_total": ("ingreso_total", "sum"),
        "unidades_vendidas": ("unidades_vendidas", "sum"),
        "dias_con_venta": ("fecha", "nunique"),
    }
    if "descripcion_producto" in agregado.columns:
        columnas_agregacion["descripcion_producto"] = ("descripcion_producto", "first")

    ranking = (
        agregado.groupby("producto_id", observed=True)
        .agg(**columnas_agregacion)
        .reset_index()
        .sort_values("ingreso_total", ascending=False)
        .head(cantidad)
        .reset_index(drop=True)
    )

    total_general = float(agregado["ingreso_total"].sum())
    if total_general > 0:
        ranking["participacion_porcentual"] = (
            ranking["ingreso_total"] / total_general * 100
        ).round(3)
        ranking["participacion_acumulada"] = ranking["participacion_porcentual"].cumsum().round(3)

    ranking["ingreso_total"] = ranking["ingreso_total"].round(2)
    ranking.insert(0, "posicion", range(1, len(ranking) + 1))
    return ranking


def enriquecer_con_calendario(datos: pd.DataFrame, copiar: bool = True) -> pd.DataFrame:
    """
    Suma a la tabla los atributos de calendario que se derivan de la fecha.
    Al respecto, tener el año, el mes y el día de la semana como columnas propias evita que cada consulta del tablero los extraiga con funciones de fecha, algo que en tablas grandes impide aprovechar los índices.
    Recibe una tabla que contiene una columna fecha, además del indicador copiar, que funciona igual que en calcular_ingreso_total (en True la función es pura, mientras que en False escribe sobre la tabla recibida para no duplicarla).
    Devuelve la tabla con las columnas de calendario agregadas.
    Conviene precisar que el día de la semana sigue la convención de pandas, donde el lunes es 0 y el domingo es 6, motivo por el cual el fin de semana se marca con los valores 5 y 6.
    Lanza KeyError en caso de que falte la columna fecha.
    """
    if "fecha" not in datos.columns:
        raise KeyError(
            "La columna fecha es indispensable para derivar los atributos de calendario. "
            "Conviene revisar el paso de ingesta, que es el que normaliza esa columna."
        )

    resultado = datos.copy() if copiar else datos
    momento = pd.to_datetime(resultado["fecha"], errors="coerce")

    resultado["anio"] = momento.dt.year.astype("Int64")
    resultado["mes"] = momento.dt.month.astype("Int64")
    resultado["dia"] = momento.dt.day.astype("Int64")
    resultado["anio_mes"] = momento.dt.strftime("%Y-%m")
    resultado["dia_semana"] = momento.dt.dayofweek.astype("Int64")
    resultado["es_fin_de_semana"] = momento.dt.dayofweek.isin([5, 6])

    return resultado
