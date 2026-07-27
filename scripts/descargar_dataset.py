"""
Descarga el conjunto de datos completo y lo deja listo para el pipeline.
Al respecto, el repositorio versiona una muestra de unas cincuenta mil filas para que cualquiera pueda clonar el proyecto y ejecutarlo sin depender de una descarga previa.
En cambio, el histórico completo supera el millón de filas y pesa demasiado para versionarlo, motivo por el cual se baja con este script cuando hace falta.
La fuente es el repositorio de aprendizaje automático de la Universidad de California en Irvine, que constituye el origen del conjunto Online Retail II.
Cabe señalar que el mismo archivo circula en Kaggle bajo el nombre de Online Retail II UCI.

Uso::

    python scripts/descargar_dataset.py
    python scripts/descargar_dataset.py --forzar
    python scripts/descargar_dataset.py --destino /otra/ruta/archivo.csv
"""

from __future__ import annotations

import argparse
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

URL_ORIGEN = "https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip"
NOMBRE_INTERNO = "online_retail_II.xlsx"
DESTINO_POR_DEFECTO = RAIZ / "datos" / "crudos" / "ventas_minoristas.csv"


def descargar(url: str) -> bytes:
    """
    Trae el archivo comprimido desde el repositorio de origen.
    Recibe la dirección del archivo a descargar y devuelve su contenido binario.
    En caso de que la descarga falle o llegue vacía, la función levanta RuntimeError con la explicación de cómo obtener el archivo a mano.
    """
    print(f"Descargando desde {url}")
    print("El archivo pesa unos cuarenta y cinco megabytes, puede tardar un rato.")

    try:
        peticion = urllib.request.Request(
            url, headers={"User-Agent": "pipeline-ventas/1.0 (proyecto educativo)"}
        )
        with urllib.request.urlopen(peticion, timeout=600) as respuesta:
            contenido = respuesta.read()
    except Exception as error:  # noqa: BLE001
        raise RuntimeError(
            f"No se pudo descargar el archivo. {error}\n"
            "Alternativa manual, bajar el archivo desde\n"
            "  https://archive.ics.uci.edu/dataset/502/online+retail+ii\n"
            "descomprimirlo y convertir el Excel a CSV en datos/crudos/."
        ) from error

    if not contenido:
        raise RuntimeError("La descarga llegó vacía.")

    print(f"Descarga completada, {len(contenido) / 1_048_576:.1f} megabytes.")
    return contenido


def convertir_a_csv(contenido_zip: bytes, destino: Path) -> int:
    """
    Extrae el Excel del comprimido y lo convierte a un único CSV.
    Al respecto, el archivo original trae dos hojas, una por cada año comercial.
    Ambas se concatenan puesto que el pipeline trabaja sobre el histórico completo y la división en hojas constituye un detalle del formato de origen y no del negocio.
    Recibe los bytes del archivo comprimido que se acaba de descargar y la ruta del CSV a generar, y devuelve la cantidad de filas escritas.
    En caso de que el comprimido no contenga el Excel esperado, la función levanta RuntimeError.
    """
    print("Extrayendo y convirtiendo a CSV. La conversión tarda unos minutos.")

    with zipfile.ZipFile(io.BytesIO(contenido_zip)) as comprimido:
        nombres = comprimido.namelist()
        candidatos = [nombre for nombre in nombres if nombre.endswith(".xlsx")]
        if not candidatos:
            raise RuntimeError(
                f"El comprimido no contiene ningún Excel. Archivos encontrados: {nombres}"
            )
        with comprimido.open(candidatos[0]) as excel:
            hojas = pd.read_excel(excel, sheet_name=None, engine="openpyxl")

    partes = []
    for nombre_hoja, tabla in hojas.items():
        print(f"  Hoja {nombre_hoja}, {len(tabla):,} filas")
        partes.append(tabla)

    completo = pd.concat(partes, ignore_index=True)

    destino.parent.mkdir(parents=True, exist_ok=True)
    completo.to_csv(destino, index=False, encoding="utf-8")

    print(f"CSV escrito en {destino}")
    print(f"Total de filas {len(completo):,}")
    print(f"Tamaño {destino.stat().st_size / 1_048_576:.1f} megabytes")
    return int(len(completo))


def analizar_argumentos(argumentos: list[str] | None = None) -> argparse.Namespace:
    """
    Define los parámetros de línea de comandos.
    Recibe la lista de argumentos a interpretar y, en caso de que se omita, toma la que dejó el intérprete en sys.argv.
    Devuelve el espacio de nombres con las opciones ya resueltas.
    """
    analizador = argparse.ArgumentParser(
        description="Descarga el histórico completo de transacciones de venta minorista"
    )
    analizador.add_argument(
        "--destino",
        type=Path,
        default=DESTINO_POR_DEFECTO,
        help="Ruta del CSV a generar",
    )
    analizador.add_argument(
        "--url",
        default=URL_ORIGEN,
        help="Dirección del archivo comprimido de origen",
    )
    analizador.add_argument(
        "--forzar",
        action="store_true",
        help="Vuelve a descargar aunque el archivo ya exista",
    )
    return analizador.parse_args(argumentos)


def main(argumentos: list[str] | None = None) -> int:
    """
    Punto de entrada del script.
    Recibe los argumentos de línea de comandos y devuelve cero cuando la descarga terminó bien y uno cuando hubo un error.
    Cabe señalar que un archivo ya presente en el destino no se vuelve a bajar, salvo que se pida con la opción de forzado.
    """
    opciones = analizar_argumentos(argumentos)

    if opciones.destino.exists() and not opciones.forzar:
        tamanio = opciones.destino.stat().st_size / 1_048_576
        print(f"El archivo ya existe en {opciones.destino} y ocupa {tamanio:.1f} megabytes.")
        print("Usar --forzar para descargarlo de nuevo.")
        return 0

    try:
        contenido = descargar(opciones.url)
        convertir_a_csv(contenido, opciones.destino)
    except Exception as error:  # noqa: BLE001
        print(f"\nError: {error}\n", file=sys.stderr)
        return 1

    print("\nListo. Ya se puede correr 'python ejecutar_pipeline.py'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
