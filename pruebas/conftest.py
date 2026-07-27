"""
Accesorios compartidos por toda la batería de pruebas.
Al respecto, la idea central consiste en que ninguna prueba dependa del conjunto de datos real ni de servicios levantados.
Cabe señalar que cada caso arma sus propios datos, con la cantidad justa de filas para ejercitar una regla concreta y con valores que se pueden verificar a mano.
De ese modo, cuando una prueba falla el problema queda a la vista sin necesidad de inspeccionar un millón de registros.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

# El paquete trabajos vive en la raíz del repositorio, un nivel por encima de esta carpeta, motivo por el cual hay que agregarlo a la ruta de importación.
RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from trabajos.configuracion import ConfiguracionPipeline  # noqa: E402


@pytest.fixture
def ventas_validas() -> pd.DataFrame:
    """
    Devuelve cinco líneas de factura que cumplen todas las reglas de calidad.
    Al respecto, los importes están elegidos para que las sumas den números redondos y se puedan comprobar sin calculadora.
    Conviene precisar que el producto 22086 aparece dos veces en la misma fecha (10 unidades a 2.50 el primero de diciembre y otras 20 unidades a 2.50 ese mismo día), de manera que se puede verificar que la agregación suma bien.
    La tabla devuelta trae el mismo esquema que produce la etapa de ingesta.
    """
    return pd.DataFrame(
        {
            "factura": ["489434", "489434", "489435", "489436", "489437"],
            "producto_id": ["22086", "85048", "22086", "21232", "84879"],
            "descripcion": [
                "PAPER CHAIN KIT 50'S CHRISTMAS",
                "15CM CHRISTMAS GLASS BALL",
                "PAPER CHAIN KIT 50'S CHRISTMAS",
                "STRAWBERRY CERAMIC TRINKET BOX",
                "ASSORTED COLOUR BIRD ORNAMENT",
            ],
            "cantidad": pd.array([10, 5, 20, 4, 8], dtype="Int64"),
            "fecha_hora": pd.to_datetime(
                [
                    "2009-12-01 07:45:00",
                    "2009-12-01 07:45:00",
                    "2009-12-01 09:10:00",
                    "2009-12-02 11:20:00",
                    "2009-12-02 15:00:00",
                ]
            ),
            "fecha": [
                pd.Timestamp("2009-12-01").date(),
                pd.Timestamp("2009-12-01").date(),
                pd.Timestamp("2009-12-01").date(),
                pd.Timestamp("2009-12-02").date(),
                pd.Timestamp("2009-12-02").date(),
            ],
            "precio_unitario": [2.50, 6.00, 2.50, 1.25, 10.00],
            "cliente_id": pd.array([13085, 13085, 13078, 13078, 13085], dtype="Int64"),
            "pais": [
                "UNITED KINGDOM",
                "UNITED KINGDOM",
                "UNITED KINGDOM",
                "FRANCE",
                "FRANCE",
            ],
        }
    )


@pytest.fixture
def ventas_con_problemas(ventas_validas: pd.DataFrame) -> pd.DataFrame:
    """
    Extiende el conjunto válido con una fila defectuosa por cada regla de calidad.
    Al respecto, cada fila agregada incumple exactamente una regla, de modo que se puede afirmar con precisión cuántos rechazos tiene que producir cada una.
    Recibe en ventas_validas el conjunto base sin problemas y devuelve una tabla de diez filas (cinco buenas y cinco defectuosas).
    """
    problematicas = pd.DataFrame(
        {
            "factura": ["C489438", "489439", "489440", "489441", "489434"],
            "producto_id": ["22086", "21232", "84879", None, "22086"],
            "descripcion": [
                "DEVOLUCION DE MERCADERIA",
                "PRECIO FUERA DE RANGO",
                "FECHA IMPOSIBLE",
                "SIN CODIGO DE PRODUCTO",
                "LINEA DUPLICADA",
            ],
            # Los defectos aparecen en el mismo orden que las filas: Cantidad negativa, precio absurdo, fecha futura, producto nulo y una repetición exacta de la primera fila del conjunto válido.
            "cantidad": pd.array([-10, 3, 5, 2, 10], dtype="Int64"),
            "fecha_hora": pd.to_datetime(
                [
                    "2009-12-03 10:00:00",
                    "2009-12-03 10:05:00",
                    "2099-01-01 10:00:00",
                    "2009-12-03 10:15:00",
                    "2009-12-01 07:45:00",
                ]
            ),
            "fecha": [
                pd.Timestamp("2009-12-03").date(),
                pd.Timestamp("2009-12-03").date(),
                pd.Timestamp("2099-01-01").date(),
                pd.Timestamp("2009-12-03").date(),
                pd.Timestamp("2009-12-01").date(),
            ],
            "precio_unitario": [2.50, 99_999.00, 3.00, 4.00, 2.50],
            "cliente_id": pd.array([13085, 13078, 13085, 13078, 13085], dtype="Int64"),
            "pais": [
                "UNITED KINGDOM",
                "UNITED KINGDOM",
                "UNITED KINGDOM",
                "UNITED KINGDOM",
                "UNITED KINGDOM",
            ],
        }
    )
    return pd.concat([ventas_validas, problematicas], ignore_index=True)


@pytest.fixture
def configuracion_temporal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ConfiguracionPipeline:
    """
    Devuelve una configuración que escribe en un directorio descartable.
    Al respecto, apunta todas las rutas a la carpeta temporal que pytest crea para el caso, de modo que las pruebas nunca tocan la carpeta de salida real ni dejan residuos entre corridas.
    Recibe en tmp_path esa carpeta exclusiva del caso y en monkeypatch la utilidad de pytest con la que se alteran las variables de entorno de las que se alimenta la configuración.
    """
    monkeypatch.setenv("DIR_DATOS", str(tmp_path / "datos"))
    monkeypatch.setenv("DIR_CRUDOS", str(tmp_path / "datos" / "crudos"))
    monkeypatch.setenv("DIR_EJEMPLOS", str(tmp_path / "datos" / "ejemplos"))
    monkeypatch.setenv("DIR_SALIDA", str(tmp_path / "salida"))
    monkeypatch.setenv("METRICAS_HABILITADAS", "false")
    monkeypatch.setenv("PUSHGATEWAY_URL", "")
    # Los conjuntos de prueba son muy chicos y concentran muchos casos defectuosos a propósito, motivo por el cual el porcentaje de rechazo resulta altísimo comparado con el de una corrida real.
    # En consecuencia, el umbral se levanta hasta 99.0 para poder ejercitar cada regla sin que la validación corte la corrida antes de tiempo.
    # Cabe señalar que las pruebas dedicadas a verificar el corte por umbral definen el suyo propio.
    monkeypatch.setenv("PORCENTAJE_RECHAZO_MAXIMO", "99.0")

    configuracion = ConfiguracionPipeline()
    configuracion.preparar_directorios()
    return configuracion


@pytest.fixture
def csv_de_prueba(tmp_path: Path, ventas_validas: pd.DataFrame) -> Path:
    """
    Escribe un archivo CSV con los encabezados originales del conjunto de datos de origen.
    Al respecto, sirve para probar la ingesta de punta a punta, incluido el renombrado de las columnas del inglés al vocabulario del proyecto.
    Los datos que se vuelcan son los de ventas_validas y lo que se devuelve es la ruta del archivo generado dentro de la carpeta temporal del caso.
    """
    original = pd.DataFrame(
        {
            "Invoice": ventas_validas["factura"],
            "StockCode": ventas_validas["producto_id"],
            "Description": ventas_validas["descripcion"],
            "Quantity": ventas_validas["cantidad"],
            "InvoiceDate": ventas_validas["fecha_hora"],
            "Price": ventas_validas["precio_unitario"],
            "Customer ID": ventas_validas["cliente_id"],
            "Country": ventas_validas["pais"],
        }
    )
    ruta = tmp_path / "ventas_prueba.csv"
    original.to_csv(ruta, index=False, encoding="utf-8")
    return ruta
