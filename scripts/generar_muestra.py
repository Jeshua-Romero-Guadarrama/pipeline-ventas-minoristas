"""
Genera la muestra versionada a partir del histórico completo.
Al respecto, la muestra que viaja en el repositorio no es un recorte al azar de filas sueltas.
Por el contrario, se eligen facturas completas y se conservan todas sus líneas, puesto que cortar una factura por la mitad rompería los conteos de comprobantes distintos y las pruebas del proyecto dejarían de tener sentido.
Adicionalmente, se fija una semilla para que el resultado sea siempre el mismo.
La razón es que una muestra que cambiara en cada corrida haría que los números de la documentación dejaran de coincidir con lo que ve quien clona el repositorio.

Uso::

    python scripts/generar_muestra.py
    python scripts/generar_muestra.py --facturas 5000
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

ORIGEN_POR_DEFECTO = RAIZ / "datos" / "crudos" / "ventas_minoristas.csv"
DESTINO_POR_DEFECTO = RAIZ / "datos" / "ejemplos" / "ventas_minoristas_muestra.csv"
SEMILLA = 42


def generar(origen: Path, destino: Path, cantidad_facturas: int) -> dict[str, object]:
    """
    Construye la muestra tomando facturas enteras del archivo completo.
    Recibe la ruta del CSV con el histórico completo, la ruta del CSV de la muestra a generar y la cantidad de facturas distintas que se quieren incluir.
    Devuelve un diccionario con las estadísticas de lo generado (filas, facturas, productos, países, fechas extremas y tamaño en disco).
    En caso de que el archivo de origen no exista, la función levanta FileNotFoundError e indica cómo descargarlo.
    """
    if not origen.exists():
        raise FileNotFoundError(
            f"No se encontró el histórico completo en {origen}. "
            "Descargarlo primero con 'python scripts/descargar_dataset.py'."
        )

    print(f"Leyendo el histórico completo desde {origen}")
    completo = pd.read_csv(origen, encoding="utf-8")
    print(f"  {len(completo):,} filas leídas")

    facturas = completo["Invoice"].astype(str).drop_duplicates()
    print(f"  {len(facturas):,} facturas distintas")

    seleccionadas = set(
        facturas.sample(n=min(cantidad_facturas, len(facturas)), random_state=SEMILLA)
    )

    muestra = completo[completo["Invoice"].astype(str).isin(seleccionadas)].copy()
    muestra["InvoiceDate"] = pd.to_datetime(muestra["InvoiceDate"], errors="coerce")
    muestra = muestra.sort_values("InvoiceDate").reset_index(drop=True)

    destino.parent.mkdir(parents=True, exist_ok=True)
    muestra.to_csv(destino, index=False, encoding="utf-8")

    estadisticas: dict[str, object] = {
        "filas": int(len(muestra)),
        "facturas": int(muestra["Invoice"].nunique()),
        "productos": int(muestra["StockCode"].nunique()),
        "paises": int(muestra["Country"].nunique()),
        "fecha_minima": str(muestra["InvoiceDate"].min()),
        "fecha_maxima": str(muestra["InvoiceDate"].max()),
        "tamanio_mb": round(destino.stat().st_size / 1_048_576, 2),
    }

    print(f"\nMuestra escrita en {destino}")
    for clave, valor in estadisticas.items():
        print(f"  {clave:15s} {valor}")

    return estadisticas


def analizar_argumentos(argumentos: list[str] | None = None) -> argparse.Namespace:
    """
    Define los parámetros de línea de comandos.
    Recibe la lista de argumentos a interpretar y, en caso de que se omita, toma la que dejó el intérprete en sys.argv.
    Devuelve el espacio de nombres con las opciones ya resueltas.
    """
    analizador = argparse.ArgumentParser(
        description="Genera la muestra versionada a partir del histórico completo"
    )
    analizador.add_argument("--origen", type=Path, default=ORIGEN_POR_DEFECTO)
    analizador.add_argument("--destino", type=Path, default=DESTINO_POR_DEFECTO)
    analizador.add_argument(
        "--facturas",
        type=int,
        default=2600,
        help="Cantidad de facturas completas a incluir en la muestra",
    )
    return analizador.parse_args(argumentos)


def main(argumentos: list[str] | None = None) -> int:
    """
    Punto de entrada del script.
    Recibe los argumentos de línea de comandos y devuelve cero cuando la muestra se generó bien y uno cuando hubo un error.
    """
    opciones = analizar_argumentos(argumentos)
    try:
        generar(opciones.origen, opciones.destino, opciones.facturas)
    except Exception as error:  # noqa: BLE001
        print(f"\nError: {error}\n", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
