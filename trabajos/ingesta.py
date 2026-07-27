"""
Etapa de ingesta del pipeline de ventas.
La responsabilidad de este módulo termina donde empieza la de las validaciones.
Al respecto, aquí solo se lee el archivo crudo, se renombran las columnas al vocabulario del proyecto y se fuerzan los tipos de datos.
No se descarta ninguna fila, ni siquiera las que a simple vista están mal, puesto que la decisión de qué se rechaza pertenece a la capa de calidad y tiene que quedar registrada ahí.
El formato de origen es el del conjunto de datos Online Retail II, un histórico real de transacciones de un comercio minorista británico de regalos que publica el repositorio de la Universidad de California en Irvine y que circula en Kaggle.
Cabe señalar que cada fila corresponde a una línea de una factura (una factura que vendió tres productos distintos ocupa tres filas con el mismo número de factura).
"""

from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd

from trabajos.configuracion import COLUMNAS_OBLIGATORIAS, MAPEO_COLUMNAS
from trabajos.registro import obtener_registrador

registrador = obtener_registrador(__name__)


class ErrorDeIngesta(Exception):
    """
    La excepción se lanza cuando el archivo de entrada no se puede procesar.
    Tener una excepción propia permite que quien orquesta el pipeline distinga un problema del origen de datos de un error de programación.
    """


def _normalizar_nombre(nombre: str) -> str:
    """
    Limpia el nombre de una columna para poder compararlo con el mapeo del proyecto.
    Recibe el nombre tal como viene en el encabezado del archivo y devuelve ese mismo nombre sin espacios en los extremos y con los espacios internos reducidos a uno solo.
    Al respecto, los archivos exportados desde planillas suelen traer espacios sobrantes o mayúsculas inconsistentes, motivo por el cual normalizar antes de mapear evita que la ingesta falle por un detalle cosmético.
    Así, un encabezado escrito como "  Customer  ID " se convierte en "Customer ID", que sí figura en el mapeo.
    """
    return " ".join(str(nombre).split())


def _renombrar_columnas(datos: pd.DataFrame) -> pd.DataFrame:
    """
    Traduce los encabezados originales al vocabulario del proyecto.
    Recibe la tabla recién leída del archivo crudo y devuelve una copia con los nombres de columna en español.
    Cabe señalar que las columnas ausentes del mapeo se conservan con su nombre original en minúsculas y con guiones bajos, de modo que un archivo con campos extra no pierde información sin aviso.
    Por ejemplo, "Price" pasa a llamarse "precio_unitario" porque figura en el mapeo, mientras que una columna añadida como "Sales Channel" queda como "sales_channel".
    """
    equivalencias: dict[str, str] = {}
    for columna in datos.columns:
        limpia = _normalizar_nombre(columna)
        if limpia in MAPEO_COLUMNAS:
            equivalencias[columna] = MAPEO_COLUMNAS[limpia]
        else:
            equivalencias[columna] = limpia.lower().replace(" ", "_")

    renombradas = datos.rename(columns=equivalencias)
    registrador.debug(
        "Columnas renombradas", extra={"equivalencias": equivalencias}
    )
    return renombradas


def _convertir_tipos(datos: pd.DataFrame) -> pd.DataFrame:
    """
    Fuerza el tipo de cada columna conocida.
    Recibe la tabla con los nombres de columna ya normalizados y devuelve una copia con los tipos ajustados.
    El modo permisivo de pandas deja como nulo todo valor que no se puede convertir, en lugar de cortar la lectura.
    En consecuencia, una cantidad escrita como "dos" no detiene la corrida (queda en nulo, la validación de nulos la detecta y la fila termina en cuarentena con su motivo, que resulta mucho más útil que una excepción sin contexto).
    """
    convertidos = datos.copy()

    if "fecha_hora" in convertidos.columns:
        convertidos["fecha_hora"] = pd.to_datetime(
            convertidos["fecha_hora"], errors="coerce", format="mixed", dayfirst=False
        )
        # El agregado final se calcula por día, motivo por el cual se guarda aparte la fecha sin la hora.
        # De ese modo, las ventas de las 09:15 y de las 18:40 del 2010-12-01 caen en la misma fila del agregado.
        convertidos["fecha"] = convertidos["fecha_hora"].dt.date

    for columna_numerica in ("cantidad",):
        if columna_numerica in convertidos.columns:
            convertidos[columna_numerica] = pd.to_numeric(
                convertidos[columna_numerica], errors="coerce"
            ).astype("Int64")

    for columna_decimal in ("precio_unitario",):
        if columna_decimal in convertidos.columns:
            convertidos[columna_decimal] = pd.to_numeric(
                convertidos[columna_decimal], errors="coerce"
            ).astype("float64")

    for columna_texto in ("factura", "producto_id", "descripcion", "pais"):
        if columna_texto in convertidos.columns:
            convertidos[columna_texto] = (
                convertidos[columna_texto].astype("string").str.strip().str.upper()
            )

    if "cliente_id" in convertidos.columns:
        # El identificador de cliente viene como decimal en el archivo original aunque conceptualmente sea un entero, de ahí que se convierta a "Int64" y no a "int64".
        # Dicho tipo admite nulos, condición indispensable porque muchas ventas de mostrador no se asocian a ningún cliente.
        # Así, el valor "17850.0" del archivo queda como 17850 y una celda vacía queda como nulo en lugar de romper la conversión.
        convertidos["cliente_id"] = pd.to_numeric(
            convertidos["cliente_id"], errors="coerce"
        ).astype("Int64")

    return convertidos


# Columnas de texto que se repiten muchísimo a lo largo del archivo.
# Al respecto, sobre un millón de filas hay unas cinco mil descripciones distintas y cuarenta y tres países, razón por la que guardar cada texto una sola vez y dejar un índice numérico en cada fila reduce el consumo de memoria de forma notable.
# En cambio, producto_id queda fuera a propósito, puesto que es clave de agrupación y de cruce, y el tipo categórico complica esas operaciones más de lo que ahorra.
COLUMNAS_REPETITIVAS: tuple[str, ...] = ("descripcion", "pais", "factura")


def _comprimir_texto(datos: pd.DataFrame) -> pd.DataFrame:
    """
    Convierte a tipo categórico las columnas de texto muy repetitivas.
    Recibe la tabla ya normalizada y con los tipos convertidos, y devuelve esa misma tabla con las columnas repetitivas en tipo categórico.
    La conversión se aplica sobre la tabla completa y no sobre cada lote, dado que dos lotes con conjuntos de categorías distintos no se pueden concatenar sin volver a convertirlo todo a texto, que es justamente lo que se quiere evitar.
    """
    for columna in COLUMNAS_REPETITIVAS:
        if columna in datos.columns:
            datos[columna] = datos[columna].astype("category")
    return datos


def detectar_separador(ruta: Path, bytes_de_muestra: int = 65_536) -> str:
    """
    Averigua qué carácter separa las columnas leyendo solo el principio del archivo.
    Recibe la ruta del archivo a inspeccionar y la cantidad de bytes iniciales que alcanza con leer para decidir.
    Devuelve el carácter separador detectado, y la coma cuando no se puede determinar ninguno.
    Existe la tentación de delegar esta tarea en pandas pasando sep=None, pero eso obliga a usar su motor escrito en Python, que consume varias veces más memoria y resulta bastante más lento que el motor en C.
    Sobre un archivo de noventa megabytes la diferencia es enorme, al punto de agotar la memoria de un contenedor.
    En cambio, leyendo unos pocos kilobytes se resuelve lo mismo y después se usa el motor rápido con el separador ya conocido.
    """
    with ruta.open("r", encoding="utf-8", errors="replace") as archivo:
        muestra = archivo.read(bytes_de_muestra)

    if not muestra:
        return ","

    try:
        dialecto = csv.Sniffer().sniff(muestra, delimiters=",;\t|")
        separador = dialecto.delimiter
    except csv.Error:
        # El detector falla con archivos de una sola columna o con contenido poco habitual.
        # En esos casos se cuenta cuál de los candidatos aparece más veces en la primera línea, que es lo que haría cualquiera a ojo.
        # Por ejemplo, en el encabezado "Invoice;StockCode;Quantity" gana el punto y coma con dos apariciones frente a ninguna de los demás candidatos.
        primera_linea = muestra.split("\n", 1)[0]
        conteos = {candidato: primera_linea.count(candidato) for candidato in ",;\t|"}
        separador = max(conteos, key=lambda clave: conteos[clave])
        if conteos[separador] == 0:
            separador = ","

    registrador.debug(
        "Separador detectado", extra={"ruta": str(ruta), "separador": repr(separador)}
    )
    return separador


def verificar_columnas(datos: pd.DataFrame) -> None:
    """
    Comprueba que la tabla traiga todas las columnas indispensables.
    Recibe la tabla con los nombres de columna ya normalizados y no devuelve nada cuando la comprobación resulta favorable.
    En caso de que falte alguna columna obligatoria, lanza ErrorDeIngesta indicando cuáles faltan y cuáles se encontraron.
    """
    faltantes = [columna for columna in COLUMNAS_OBLIGATORIAS if columna not in datos.columns]
    if faltantes:
        raise ErrorDeIngesta(
            "El archivo de entrada no tiene las columnas obligatorias "
            f"{faltantes}, sin las cuales no se puede calcular el ingreso por producto y fecha. "
            f"Las columnas encontradas fueron {sorted(datos.columns)}. "
            "Conviene revisar el encabezado del archivo y, si el origen usa otros nombres, agregarlos a MAPEO_COLUMNAS en trabajos/configuracion.py."
        )


def _leer_csv_por_lotes(
    ruta: Path, filas_maximas: int | None, tamanio_lote: int
) -> pd.DataFrame:
    """
    Lee un CSV en bloques y normaliza cada bloque antes de acumularlo.
    Recibe la ruta del archivo, el límite total de filas (None para leer todo) y la cantidad de filas que componen cada bloque.
    Devuelve la tabla completa con los nombres traducidos y los tipos convertidos, y lanza ErrorDeIngesta en caso de que el archivo no traiga las columnas obligatorias.
    La lectura por bloques es la diferencia entre que el pipeline entre o no entre en un contenedor con memoria acotada.
    Al respecto, leer el archivo entero de una vez deja en memoria un millón de filas con ocho columnas de objetos de Python, que es la estructura más costosa de todo el recorrido.
    En cambio, al convertir cada bloque apenas se lee, esa representación cara nunca existe completa (solo vive un bloque a la vez).
    """
    separador = detectar_separador(ruta)
    partes: list[pd.DataFrame] = []
    filas_acumuladas = 0

    lector = pd.read_csv(
        ruta,
        sep=separador,
        # El motor en C es el que usa pandas por defecto y resulta varias veces más rápido y más liviano que el escrito en Python.
        # Aun así, se deja explícito para que nadie lo cambie por descuido al agregar alguna opción que solo admita el otro motor.
        engine="c",
        encoding="utf-8",
        encoding_errors="replace",
        on_bad_lines="warn",
        chunksize=tamanio_lote,
    )

    with lector:
        for numero, lote in enumerate(lector):
            renombrado = _renombrar_columnas(lote)

            # La comprobación de columnas se hace una sola vez, sobre el primer bloque.
            # Puesto que el encabezado es único, si está mal lo está para todo el archivo, motivo por el cual cortar aquí evita leer noventa megabytes para nada.
            if numero == 0:
                verificar_columnas(renombrado)

            if filas_maximas is not None:
                restantes = filas_maximas - filas_acumuladas
                if restantes <= 0:
                    break
                if len(renombrado) > restantes:
                    renombrado = renombrado.head(restantes)

            partes.append(_convertir_tipos(renombrado))
            filas_acumuladas += len(renombrado)

            if filas_maximas is not None and filas_acumuladas >= filas_maximas:
                break

    if not partes:
        return pd.DataFrame()

    completo = pd.concat(partes, ignore_index=True, copy=False)
    # Las partes ya no hacen falta y entre todas ocupan lo mismo que el resultado recién concatenado.
    # Por ello se vacía la lista, de modo que el recolector de basura las libere antes de que arranque la etapa siguiente.
    partes.clear()

    return completo


def leer_archivo(
    ruta: Path, filas_maximas: int | None = None, tamanio_lote: int = 200_000
) -> pd.DataFrame:
    """
    Lee el archivo crudo desde disco y devuelve una tabla normalizada, con las columnas en español y los tipos convertidos.
    Acepta CSV con separador de coma o de punto y coma, y también Parquet, que es lo que suele haber cuando el archivo ya pasó por otro proceso.
    Recibe la ubicación del archivo a leer.
    Adicionalmente admite un límite de filas, útil para probar el pipeline con una muestra reducida, y el tamaño del lote que se lee y convierte por vez (bajarlo reduce el pico de memoria a costa de algo de velocidad).
    Lanza ErrorDeIngesta cuando el archivo no existe, cuando está vacío, cuando tiene un formato no soportado o cuando le faltan columnas obligatorias.
    """
    if not ruta.exists():
        raise ErrorDeIngesta(
            f"No se encontró el archivo de entrada en {ruta}, de modo que la ingesta no tiene nada que leer. "
            "Para resolverlo se descarga el histórico con 'python scripts/descargar_dataset.py' "
            "o se copia el CSV original a datos/crudos/."
        )

    sufijo = ruta.suffix.lower()
    registrador.info(
        "Iniciando lectura del archivo crudo",
        extra={"ruta": str(ruta), "formato": sufijo, "limite_filas": filas_maximas},
    )

    try:
        if sufijo == ".parquet":
            crudo = pd.read_parquet(ruta)
            if filas_maximas is not None:
                crudo = crudo.head(filas_maximas)
            crudo = _renombrar_columnas(crudo)
            verificar_columnas(crudo)
            tipado = _convertir_tipos(crudo)
        elif sufijo in {".csv", ".txt"}:
            tipado = _leer_csv_por_lotes(ruta, filas_maximas, tamanio_lote)
        else:
            raise ErrorDeIngesta(
                f"Formato de archivo no soportado, dado que la extensión {sufijo} no está contemplada. "
                "Los formatos admitidos son .csv, .txt y .parquet, motivo por el cual conviene convertir el "
                "archivo a alguno de esos formatos o corregir la variable de entorno ARCHIVO_ENTRADA."
            )
    except ErrorDeIngesta:
        raise
    except Exception as error:  # noqa: BLE001
        raise ErrorDeIngesta(
            f"Falló la lectura de {ruta} y la causa reportada fue \"{error}\". "
            "Conviene comprobar que el archivo no esté truncado, que su codificación sea UTF-8 "
            "y que el separador de columnas sea uniforme en todas las líneas."
        ) from error

    if tipado.empty:
        raise ErrorDeIngesta(
            f"El archivo {ruta} no contiene ninguna fila de datos, solamente el encabezado o nada en absoluto. "
            "Conviene verificar que la descarga haya terminado y que el archivo pese lo esperado antes de repetir la corrida."
        )

    tipado = _comprimir_texto(tipado)

    registrador.info(
        "Lectura completada",
        extra={
            "filas": int(len(tipado)),
            "columnas": int(len(tipado.columns)),
            "memoria_mb": round(tipado.memory_usage(deep=True).sum() / 1_048_576, 2),
        },
    )
    return tipado


def resumir_ingesta(datos: pd.DataFrame) -> dict[str, object]:
    """
    Arma un resumen descriptivo de lo que se acaba de leer.
    Recibe la tabla ya normalizada por leer_archivo y devuelve un diccionario con los conteos, el rango de fechas y las cardinalidades.
    Dicho resumen se escribe en el log y también se guarda como reporte, lo que da un punto de comparación rápido cuando una corrida trae menos datos de los esperados.
    """
    resumen: dict[str, object] = {
        "filas_totales": int(len(datos)),
        "columnas": list(datos.columns),
        "nulos_por_columna": {
            str(columna): int(datos[columna].isna().sum()) for columna in datos.columns
        },
    }

    if "fecha" in datos.columns and datos["fecha"].notna().any():
        resumen["fecha_minima"] = str(datos["fecha"].min())
        resumen["fecha_maxima"] = str(datos["fecha"].max())

    for columna in ("producto_id", "factura", "cliente_id", "pais"):
        if columna in datos.columns:
            resumen[f"distintos_{columna}"] = int(datos[columna].nunique(dropna=True))

    return resumen
