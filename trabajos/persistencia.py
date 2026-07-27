"""
Escritura de los resultados del pipeline en disco.
El formato principal es Parquet, elección que responde a tres motivos concretos.
En primer lugar, guarda el esquema junto con los datos, de manera que no hay que adivinar tipos al volver a leer.
A continuación, comprime por columna y ocupa mucho menos espacio que un CSV equivalente.
Por último, permite leer solo las columnas necesarias, lo que acelera bastante cuando el consumidor pide dos de quince columnas.
Adicionalmente, se escribe una copia en CSV del agregado principal, puesto que es el formato que cualquiera abre en una planilla sin instalar nada (en la práctica eso resuelve la mitad de los pedidos que llegan al equipo de datos).
"""

from __future__ import annotations

import json
import shutil
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from trabajos.registro import obtener_registrador

registrador = obtener_registrador(__name__)

# Zstandard es la compresión elegida por defecto, porque alcanza mejor razón de compresión que snappy con un costo de procesador parecido.
# A ello se suma que todas las herramientas del stack la leen sin configuración extra.
COMPRESION_PARQUET = "zstd"

# La precisión con la que se escriben las marcas de tiempo parece un detalle menor y no lo es.
# Al respecto, pandas maneja fechas con precisión de nanosegundos y, si se lo deja, las escribe así en el Parquet.
# Sin embargo, Spark 3.5 no sabe leer ese tipo y falla con "Illegal Parquet type: INT64 (TIMESTAMP(NANOS))", un mensaje que no dice nada sobre su causa real.
# Forzar microsegundos resuelve el problema sin perder información, dado que la granularidad de los datos son minutos (una venta registrada a las 14:35:00 conserva su valor exacto al truncar por debajo del microsegundo).
PRECISION_MARCAS_DE_TIEMPO = "us"


class ErrorDePersistencia(Exception):
    """
    Señala que un resultado del pipeline no se pudo escribir o volver a leer en disco.
    """


def _serializador_json(valor: Any) -> str:
    """
    Convierte a texto los tipos que el módulo json no sabe manejar por su cuenta.
    Recibe el objeto que la serialización dejó pendiente y devuelve una representación textual suya.
    Cabe señalar que las fechas se escriben en formato ISO 8601 (una corrida del 2011-12-09 queda como "2011-12-09"), mientras que el resto de los tipos cae en la conversión genérica a texto.
    """
    # pd.Timestamp hereda de datetime, motivo por el cual esta única comprobación cubre también las marcas de tiempo que devuelve pandas.
    if isinstance(valor, datetime | date):
        return valor.isoformat()
    return str(valor)


def _limpiar_destino(ruta: Path) -> None:
    """
    Borra el destino anterior, que es lo que vuelve idempotente a la escritura.
    Sin este paso, correr otra vez el pipeline sobre una carpeta particionada dejaría conviviendo los archivos de la corrida vieja con los de la nueva, de modo que los conteos saldrían duplicados.
    Recibe el archivo o la carpeta que corresponde eliminar, y no hace nada en caso de que la ruta todavía no exista.
    Lanza ErrorDePersistencia siempre que el destino exista pero el sistema operativo no permita borrarlo.
    """
    try:
        if ruta.is_dir():
            shutil.rmtree(ruta)
        elif ruta.exists():
            ruta.unlink()
    except PermissionError as error:
        # La situación aparece siempre que se mezclan corridas dentro y fuera de Docker sobre la misma carpeta montada.
        # Al respecto, los archivos que dejó una corrida pertenecen a un usuario y la siguiente se ejecuta como otro, razón por la que no puede borrarlos.
        # El mensaje por defecto del sistema operativo no da ninguna pista sobre ese origen, motivo por el cual se reemplaza por uno que sí explica qué hacer.
        raise ErrorDePersistencia(
            f"No se pudo borrar el resultado anterior en {ruta} por falta de permisos. "
            "Suele ocurrir cuando la carpeta de salida tiene archivos escritos por "
            "otro usuario, por ejemplo al alternar entre correr el pipeline en la "
            "máquina y dentro de un contenedor. La solución consiste en vaciar la carpeta "
            f"de salida antes de volver a ejecutar. Detalle del sistema: {error}"
        ) from error


def guardar_parquet(
    datos: pd.DataFrame,
    ruta: Path,
    columnas_particion: list[str] | None = None,
) -> Path:
    """
    Escribe una tabla en formato Parquet y devuelve la ruta efectivamente escrita.
    Recibe los datos, el destino en disco y, cuando corresponde, las columnas por las que conviene particionar.
    Siempre que se indiquen columnas de partición, el resultado es una carpeta con subcarpetas por valor.
    Al respecto, particionar por año y mes permite que una consulta acotada a un mes lea un puñado de archivos en lugar de todo el histórico (pedir diciembre de 2011 toca la subcarpeta anio=2011/mes=12 y ninguna otra).
    Lanza ErrorDePersistencia en caso de que la escritura falle por cualquier motivo.
    """
    ruta.parent.mkdir(parents=True, exist_ok=True)
    _limpiar_destino(ruta)

    # Parquet no admite el tipo date de Python, motivo por el cual esas columnas se llevan a marca de tiempo antes de escribir.
    preparados = datos.copy()
    for columna in preparados.columns:
        if preparados[columna].dtype == "object":
            muestra = preparados[columna].dropna().head(1)
            if not muestra.empty and isinstance(muestra.iloc[0], date):
                preparados[columna] = pd.to_datetime(preparados[columna], errors="coerce")

    # Las opciones comunes a los dos modos de escritura se definen una sola vez.
    # De ese modo, la salida particionada y la que no lo está producen archivos idénticos en todo salvo la disposición en carpetas.
    opciones = {
        "engine": "pyarrow",
        "compression": COMPRESION_PARQUET,
        "index": False,
        "coerce_timestamps": PRECISION_MARCAS_DE_TIEMPO,
        "allow_truncated_timestamps": True,
    }

    try:
        if columnas_particion:
            preparados.to_parquet(ruta, partition_cols=columnas_particion, **opciones)
        else:
            ruta.mkdir(parents=True, exist_ok=True)
            preparados.to_parquet(ruta / "parte-0000.parquet", **opciones)
    except Exception as error:  # noqa: BLE001
        raise ErrorDePersistencia(f"No se pudo escribir Parquet en {ruta}: {error}") from error

    tamanio = sum(f.stat().st_size for f in ruta.rglob("*.parquet")) if ruta.is_dir() else 0
    registrador.info(
        "Parquet escrito correctamente",
        extra={
            "ruta": str(ruta),
            "filas": int(len(preparados)),
            "particiones": columnas_particion or [],
            "tamanio_kb": round(tamanio / 1024, 2),
        },
    )
    return ruta


def guardar_csv(datos: pd.DataFrame, ruta: Path) -> Path:
    """
    Escribe una tabla en CSV con codificación UTF-8 y devuelve la ruta escrita.
    Recibe los datos y el archivo de destino, cuya carpeta se crea si todavía no existe.
    Cabe señalar que el índice no se escribe, porque solo agregaría una columna sin significado de negocio a un archivo pensado para abrirse en una planilla.
    Lanza ErrorDePersistencia en caso de que la escritura falle.
    """
    ruta.parent.mkdir(parents=True, exist_ok=True)
    try:
        datos.to_csv(ruta, index=False, encoding="utf-8")
    except Exception as error:  # noqa: BLE001
        raise ErrorDePersistencia(f"No se pudo escribir el CSV en {ruta}: {error}") from error

    registrador.info(
        "CSV escrito correctamente",
        extra={
            "ruta": str(ruta),
            "filas": int(len(datos)),
            "tamanio_kb": round(ruta.stat().st_size / 1024, 2),
        },
    )
    return ruta


def guardar_reporte(contenido: dict[str, Any], ruta: Path) -> Path:
    """
    Guarda el reporte de la corrida en formato JSON legible y devuelve la ruta escrita.
    Recibe el diccionario con la información del reporte y el archivo de destino.
    Al respecto, la escritura conserva los acentos y sangra con dos espacios, puesto que este archivo se lee a ojo cuando hace falta reconstruir qué pasó en una corrida.
    Lanza ErrorDePersistencia en caso de que la escritura falle.
    """
    ruta.parent.mkdir(parents=True, exist_ok=True)
    try:
        ruta.write_text(
            json.dumps(contenido, ensure_ascii=False, indent=2, default=_serializador_json),
            encoding="utf-8",
        )
    except Exception as error:  # noqa: BLE001
        raise ErrorDePersistencia(f"No se pudo escribir el reporte en {ruta}: {error}") from error

    registrador.info("Reporte guardado", extra={"ruta": str(ruta)})
    return ruta


def guardar_cuarentena(rechazados: pd.DataFrame, directorio: Path, marca: str) -> Path | None:
    """
    Persiste las filas rechazadas por las validaciones para que se puedan auditar después.
    Recibe esas filas junto con su motivo de rechazo, la carpeta donde se acumulan las cuarentenas y el identificador de la corrida, que pasa a formar parte del nombre del archivo.
    El formato es CSV a propósito, dado que quien revisa una cuarentena suele ser una persona de negocio que busca entender por qué falta un registro y necesita abrirlo con las herramientas que ya tiene.
    Devuelve la ruta escrita, o bien None cuando no hubo ninguna fila para guardar.
    """
    if rechazados.empty:
        registrador.info("No hubo filas rechazadas, no se genera archivo de cuarentena")
        return None

    directorio.mkdir(parents=True, exist_ok=True)
    ruta = directorio / f"rechazados_{marca}.csv"
    rechazados.to_csv(ruta, index=False, encoding="utf-8")

    registrador.warning(
        "Filas enviadas a cuarentena",
        extra={
            "ruta": str(ruta),
            "filas": int(len(rechazados)),
            "motivos": rechazados["motivo_rechazo"].value_counts().to_dict()
            if "motivo_rechazo" in rechazados.columns
            else {},
        },
    )
    return ruta


def leer_parquet(ruta: Path) -> pd.DataFrame:
    """
    Vuelve a leer un resultado guardado en Parquet y devuelve la tabla reconstruida.
    Recibe el archivo o la carpeta que corresponde leer.
    Al respecto, se usa en las verificaciones posteriores a la escritura y en las pruebas de extremo a extremo, donde interesa comprobar que lo que quedó en disco coincide con lo que se calculó en memoria.
    Lanza ErrorDePersistencia siempre que la ruta no exista o la lectura falle.
    """
    if not ruta.exists():
        raise ErrorDePersistencia(
            f"No existe el Parquet en {ruta}. "
            "Conviene comprobar que el pipeline haya terminado de escribir sus resultados antes de intentar leerlos."
        )
    try:
        return pd.read_parquet(ruta, engine="pyarrow")
    except Exception as error:  # noqa: BLE001
        raise ErrorDePersistencia(f"No se pudo leer el Parquet de {ruta}: {error}") from error
