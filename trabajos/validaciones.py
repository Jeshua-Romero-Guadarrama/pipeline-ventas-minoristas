"""
Capa de calidad de datos del pipeline.
El enfoque no consiste en fallar ante el primer registro sospechoso sino en separar el grano de la paja y dejar constancia de todo lo que se descartó.
Al respecto, cada fila rechazada se guarda en cuarentena junto con el motivo, de modo que alguien pueda revisarla más tarde y decidir si conviene corregir el origen o ajustar la regla.
Ahora bien, el pipeline sí se detiene cuando el porcentaje de rechazo supera un umbral configurable.
La lógica de ese corte es que perder un uno por ciento de las filas constituye el ruido normal de un sistema transaccional, mientras que perder la mitad significa que algo cambió en el origen (publicar ese resultado sería peor que no publicar nada).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import pandas as pd

from trabajos.configuracion import COLUMNAS_SIN_NULOS, ConfiguracionPipeline
from trabajos.registro import obtener_registrador

registrador = obtener_registrador(__name__)


class ErrorDeCalidad(Exception):
    """
    La excepción se lanza cuando los datos no alcanzan el nivel mínimo aceptable y, en consecuencia, no se deben publicar.
    """


@dataclass
class ResultadoValidacion:
    """
    Contiene el resultado completo de la etapa de calidad.
    En validos quedan las filas que superaron todas las reglas y en rechazados las que se descartaron, con una columna extra llamada motivo_rechazo que explica por cuál regla cayó cada una.
    Adicionalmente, conteo_por_regla indica cuántas filas descartó cada regla y filas_entrada guarda el total que había antes de validar, cifra que permite calcular el porcentaje de rechazo.
    """

    validos: pd.DataFrame
    rechazados: pd.DataFrame
    conteo_por_regla: dict[str, int] = field(default_factory=dict)
    filas_entrada: int = 0

    @property
    def filas_validas(self) -> int:
        """
        Cantidad de filas que sobrevivieron a la validación.
        """
        return int(len(self.validos))

    @property
    def filas_rechazadas(self) -> int:
        """
        Cantidad de filas enviadas a cuarentena.
        """
        return int(len(self.rechazados))

    @property
    def porcentaje_rechazo(self) -> float:
        """
        Proporción de filas descartadas sobre el total de entrada, expresada en por ciento y redondeada a cuatro decimales.
        De ese modo, cien filas de entrada con tres rechazadas dan 3.0 como resultado.
        En caso de que no haya entrado ninguna fila, se devuelve 0.0 para no dividir entre cero.
        """
        if self.filas_entrada == 0:
            return 0.0
        return round(self.filas_rechazadas / self.filas_entrada * 100, 4)

    def a_diccionario(self) -> dict[str, object]:
        """
        Convierte el resultado en un diccionario serializable a JSON, con los conteos generales y el detalle por regla.
        Cabe señalar que las dos tablas quedan fuera a propósito, puesto que el destino de este diccionario son el log y el reporte de calidad.
        """
        return {
            "filas_entrada": self.filas_entrada,
            "filas_validas": self.filas_validas,
            "filas_rechazadas": self.filas_rechazadas,
            "porcentaje_rechazo": self.porcentaje_rechazo,
            "conteo_por_regla": dict(self.conteo_por_regla),
        }


@dataclass(frozen=True)
class ReglaCalidad:
    """
    Define una regla de calidad aplicable a la tabla de ventas.
    En nombre va el identificador corto que se usa en métricas y reportes, y en descripcion la explicación en lenguaje llano de qué comprueba.
    Por su parte, detectar es una función que recibe la tabla y devuelve una máscara booleana donde True marca las filas que incumplen la regla.
    Conviene precisar que la máscara señala lo que se rechaza y no lo que se conserva, de modo que una regla que no encuentra nada malo devuelve una máscara íntegramente en False.
    """

    nombre: str
    descripcion: str
    detectar: Callable[[pd.DataFrame], pd.Series]


def construir_reglas(configuracion: ConfiguracionPipeline) -> list[ReglaCalidad]:
    """
    Arma el catálogo de reglas usando los umbrales de cantidad y de precio que trae la configuración recibida.
    Devuelve una lista ordenada de reglas, y ese orden define la prioridad del motivo que se asigna a una fila que incumple más de una regla a la vez.
    Así, una fila fechada en 2099 y con cantidad negativa queda registrada con el motivo fecha_dentro_de_rango y no con cantidad_minima, puesto que la regla de la fecha aparece antes en la lista.
    Las reglas se construyen dentro de una función y no como constantes de módulo, dado que los umbrales vienen del entorno y tienen que poder cambiar entre corridas.
    """

    def sin_valores_nulos(datos: pd.DataFrame) -> pd.Series:
        """
        Marca las filas que traen algún nulo en las columnas indispensables, es decir, producto_id, cantidad, fecha_hora y precio_unitario.
        Una línea de factura sin precio unitario no permite calcular ingreso alguno, motivo por el cual se descarta en lugar de arrastrar un cero que falsearía el agregado.
        En cambio, cliente_id queda fuera de esta comprobación, puesto que las ventas de mostrador no se asocian a ningún cliente y aun así son ventas reales.
        """
        presentes = [columna for columna in COLUMNAS_SIN_NULOS if columna in datos.columns]
        if not presentes:
            return pd.Series(False, index=datos.index)
        return datos[presentes].isna().any(axis=1)

    def cantidad_positiva(datos: pd.DataFrame) -> pd.Series:
        """
        Marca las filas cuya cantidad no llega al mínimo configurado, que por omisión es de una unidad.
        En el conjunto original las devoluciones se registran con cantidad negativa, de manera que una línea con cantidad menos doce corresponde a doce piezas devueltas y no a una venta.
        Dichas filas se apartan a propósito, puesto que el objetivo del pipeline es medir ingresos por venta y mezclarlas distorsionaría el agregado.
        Cabe señalar que una cantidad nula se trata como cero y, en consecuencia, también queda rechazada.
        """
        if "cantidad" not in datos.columns:
            return pd.Series(False, index=datos.index)
        return datos["cantidad"].fillna(0) < configuracion.cantidad_minima

    def precio_en_rango(datos: pd.DataFrame) -> pd.Series:
        """
        Marca las filas cuyo precio unitario queda por debajo del mínimo configurado o por encima del máximo, que por omisión son 0.01 y 50000.0.
        El límite inferior descarta los precios de cero y los negativos, que en el origen suelen corresponder a ajustes de inventario y no a ventas.
        Por su parte, el límite superior atrapa las cargas administrativas que el comercio registra como si fueran productos, tales como una línea de "AMAZON FEE" con un importe de varios miles que no corresponde a ninguna venta real.
        Adicionalmente, un precio nulo se sustituye por menos uno antes de comparar, de modo que también cae del lado rechazado.
        """
        if "precio_unitario" not in datos.columns:
            return pd.Series(False, index=datos.index)
        precio = datos["precio_unitario"].fillna(-1.0)
        return (precio < configuracion.precio_minimo) | (precio > configuracion.precio_maximo)

    def fecha_valida(datos: pd.DataFrame) -> pd.Series:
        """
        Marca las filas cuya fecha no se pudo interpretar o cae fuera del rango admitido, que va del primero de enero del año 2000 hasta el final del día en que corre el pipeline.
        Al respecto, una fecha posterior al momento de la corrida indica un error de carga en el origen y no un dato del futuro, de ahí que se rechace una línea fechada en 2099.
        El límite inferior cumple la misma función frente a las fechas por omisión de los sistemas antiguos, como el 1900-01-01 que aparece cuando el campo llegó vacío.
        """
        if "fecha_hora" not in datos.columns:
            return pd.Series(False, index=datos.index)
        momento = pd.to_datetime(datos["fecha_hora"], errors="coerce")
        limite_inferior = pd.Timestamp("2000-01-01")
        limite_superior = pd.Timestamp.now().normalize() + pd.Timedelta(days=1)
        return momento.isna() | (momento < limite_inferior) | (momento >= limite_superior)

    def producto_identificable(datos: pd.DataFrame) -> pd.Series:
        """
        Marca las filas que no traen un identificador de producto utilizable, sea porque viene nulo o porque queda vacío al quitarle los espacios.
        Sin ese identificador la fila no se puede agrupar en el agregado por producto y fecha, motivo por el cual no tiene sentido conservarla.
        Así, un valor como "   " se rechaza mientras que "85123A" se conserva.
        """
        if "producto_id" not in datos.columns:
            return pd.Series(False, index=datos.index)
        texto = datos["producto_id"].astype("string").str.strip()
        return texto.isna() | (texto.str.len() == 0)

    def sin_duplicados_exactos(datos: pd.DataFrame) -> pd.Series:
        """
        Marca las repeticiones exactas de la misma línea de factura, entendiendo por línea la combinación de factura, producto, fecha con hora, cantidad y precio unitario.
        Al respecto, una reejecución parcial del proceso de origen puede insertar la misma línea dos veces, de modo que se conserva la primera aparición y se descarta el resto.
        Conviene precisar que dos líneas de la misma factura con el mismo producto pero distinta hora no se consideran duplicadas, puesto que corresponden a dos registros que el comercio hizo por separado.
        Adicionalmente, la comprobación se omite cuando la tabla trae menos de tres de esas cinco columnas, dado que con tan poca información la coincidencia dejaría de ser evidencia de duplicado.
        """
        claves = [
            columna
            for columna in ("factura", "producto_id", "fecha_hora", "cantidad", "precio_unitario")
            if columna in datos.columns
        ]
        if len(claves) < 3:
            return pd.Series(False, index=datos.index)
        return datos.duplicated(subset=claves, keep="first")

    return [
        ReglaCalidad(
            nombre="columnas_obligatorias_sin_nulos",
            descripcion="Ninguna columna clave puede venir vacía",
            detectar=sin_valores_nulos,
        ),
        ReglaCalidad(
            nombre="producto_identificable",
            descripcion="Toda fila necesita un identificador de producto no vacío",
            detectar=producto_identificable,
        ),
        ReglaCalidad(
            nombre="fecha_dentro_de_rango",
            descripcion="La fecha debe ser interpretable y no puede ser futura",
            detectar=fecha_valida,
        ),
        ReglaCalidad(
            nombre="cantidad_minima",
            descripcion=(
                f"La cantidad tiene que ser mayor o igual a {configuracion.cantidad_minima}"
            ),
            detectar=cantidad_positiva,
        ),
        ReglaCalidad(
            nombre="precio_en_rango",
            descripcion=(
                f"El precio unitario debe estar entre {configuracion.precio_minimo} "
                f"y {configuracion.precio_maximo}"
            ),
            detectar=precio_en_rango,
        ),
        ReglaCalidad(
            nombre="sin_duplicados_exactos",
            descripcion="No se admite la misma línea de factura repetida",
            detectar=sin_duplicados_exactos,
        ),
    ]


def validar(datos: pd.DataFrame, configuracion: ConfiguracionPipeline) -> ResultadoValidacion:
    """
    Aplica todas las reglas de calidad y separa las filas válidas de las rechazadas.
    Recibe la tabla proveniente de la etapa de ingesta junto con la configuración que fija los umbrales de las reglas, y devuelve un ResultadoValidacion con las dos tablas y el detalle de conteos.
    Cada fila recibe como motivo el nombre de la primera regla que incumple, siguiendo el orden del catálogo.
    Un motivo único por fila resulta preferible a una lista de motivos, porque de ese modo el conteo por regla suma exactamente el total de rechazos y el análisis posterior no necesita desanidar nada.
    Lanza ErrorDeCalidad cuando no queda ninguna fila válida o cuando el porcentaje de rechazo supera el máximo tolerado.
    """
    filas_entrada = int(len(datos))
    reglas = construir_reglas(configuracion)

    # La serie motivo guarda, para cada fila, el nombre de la regla que la descartó, y queda en nulo mientras la fila siga siendo válida.
    # De ese modo, el nulo funciona como marca de fila todavía viva y evita llevar una máscara booleana aparte.
    motivo = pd.Series(pd.NA, index=datos.index, dtype="string")
    conteo_por_regla: dict[str, int] = {}

    for regla in reglas:
        incumple = regla.detectar(datos).fillna(True)
        # Solo se asigna motivo a las filas que todavía no fueron rechazadas, con lo cual una fila que incumple tres reglas se cuenta una sola vez y conserva el motivo de la primera.
        nuevas = incumple & motivo.isna()
        cantidad = int(nuevas.sum())
        conteo_por_regla[regla.nombre] = cantidad
        motivo = motivo.mask(nuevas, regla.nombre)

        if cantidad:
            registrador.warning(
                "Regla de calidad con incumplimientos",
                extra={
                    "regla": regla.nombre,
                    "descripcion": regla.descripcion,
                    "filas_afectadas": cantidad,
                },
            )

    mascara_rechazo = motivo.notna()
    validos = datos.loc[~mascara_rechazo].copy()
    rechazados = datos.loc[mascara_rechazo].copy()
    rechazados["motivo_rechazo"] = motivo.loc[mascara_rechazo]

    resultado = ResultadoValidacion(
        validos=validos,
        rechazados=rechazados,
        conteo_por_regla=conteo_por_regla,
        filas_entrada=filas_entrada,
    )

    registrador.info(
        "Validación de calidad finalizada",
        extra=resultado.a_diccionario(),
    )

    if resultado.filas_validas == 0:
        raise ErrorDeCalidad(
            "Ninguna fila superó las reglas de calidad, de manera que no queda nada que publicar. "
            f"El detalle por regla fue {conteo_por_regla}, conteo que muestra dónde se concentró el rechazo. "
            "Conviene revisar el archivo de entrada y el reporte de cuarentena antes de repetir la corrida."
        )

    if resultado.porcentaje_rechazo > configuracion.porcentaje_rechazo_maximo:
        raise ErrorDeCalidad(
            f"El rechazo alcanzó el {resultado.porcentaje_rechazo} por ciento de las filas, "
            f"por encima del máximo tolerado de {configuracion.porcentaje_rechazo_maximo} por ciento, "
            "lo que suele indicar que el formato del origen cambió y no que los datos traigan ruido normal. "
            f"El detalle por regla fue {conteo_por_regla}. "
            "Conviene revisar la cuarentena y, si el resultado resulta correcto, subir PORCENTAJE_RECHAZO_MAXIMO de forma deliberada."
        )

    return resultado


def verificar_agregado(agregado: pd.DataFrame) -> dict[str, object]:
    """
    Comprueba las invariantes del resultado final antes de publicarlo.
    Recibe la tabla agregada por fecha y producto, y devuelve un diccionario con el detalle de las comprobaciones realizadas.
    Las comprobaciones de salida cierran el círculo, dado que las reglas anteriores miran los datos de entrada mientras que aquí se mira el resultado, que es lo que van a consumir los tableros.
    Las invariantes verificadas son que el agregado no esté vacío, que traiga las columnas fecha, producto_id e ingreso_total, que ningún ingreso resulte negativo ni nulo y que la pareja de fecha y producto no se repita.
    Al respecto, un ingreso negativo en la salida delataría que alguna devolución se coló pese a la regla de cantidad mínima, y una pareja repetida delataría que la agrupación se hizo por las columnas equivocadas.
    Lanza ErrorDeCalidad en caso de que alguna de esas invariantes no se cumpla.
    """
    problemas: list[str] = []

    if agregado.empty:
        problemas.append("El agregado final quedó vacío")

    columnas_esperadas = {"fecha", "producto_id", "ingreso_total"}
    faltantes = columnas_esperadas - set(agregado.columns)
    if faltantes:
        problemas.append(f"Al agregado le faltan columnas: {sorted(faltantes)}")

    if "ingreso_total" in agregado.columns:
        negativos = int((agregado["ingreso_total"] < 0).sum())
        if negativos:
            problemas.append(f"Hay {negativos} filas con ingreso total negativo")
        nulos = int(agregado["ingreso_total"].isna().sum())
        if nulos:
            problemas.append(f"Hay {nulos} filas con ingreso total nulo")

    duplicados = 0
    if {"fecha", "producto_id"}.issubset(agregado.columns):
        duplicados = int(agregado.duplicated(subset=["fecha", "producto_id"]).sum())
        if duplicados:
            problemas.append(
                f"La clave fecha más producto se repite en {duplicados} filas del agregado"
            )

    detalle: dict[str, object] = {
        "filas_agregado": int(len(agregado)),
        "claves_duplicadas": duplicados,
        "problemas": problemas,
    }

    if problemas:
        registrador.error("El agregado final no pasó las comprobaciones", extra=detalle)
        raise ErrorDeCalidad(
            f"El agregado final tiene problemas: {'; '.join(problemas)}. "
            "Puesto que estas comprobaciones miran la salida y no la entrada, el fallo apunta a la etapa "
            "de transformación y no al archivo crudo, de modo que conviene revisar el cálculo del ingreso "
            "y las columnas por las que se agrupa."
        )

    registrador.info("El agregado final superó todas las comprobaciones", extra=detalle)
    return detalle
