"""
Configuración central del pipeline de ventas.
Al respecto, todo lo que puede cambiar de un entorno a otro vive en este módulo, de modo que ningún otro archivo arma rutas a mano ni lee variables de entorno por su cuenta.
En consecuencia, cuando el pipeline pasa de la notebook de alguien a un contenedor de Airflow, solo cambian las variables de entorno y el código queda intacto.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# La raíz del repositorio se calcula a partir de la ubicación de este archivo.
# De ese modo el cálculo sirve tanto en local como dentro del contenedor, donde el proyecto se monta en /opt/proyecto.
RAIZ_PROYECTO = Path(__file__).resolve().parent.parent


def _variable(nombre: str, valor_por_defecto: str) -> str:
    """
    Devuelve el contenido de una variable de entorno o, en su defecto, el valor por defecto que se le indique.
    Recibe el nombre de la variable a buscar y el valor que corresponde usar cuando esa variable no está definida o llega vacía.
    La lectura se envuelve en una función propia para poder cambiar más adelante el origen de la configuración (por ejemplo un gestor de secretos) sin tocar el resto del proyecto.
    """
    valor = os.environ.get(nombre, "").strip()
    return valor if valor else valor_por_defecto


def _ruta(nombre_variable: str, ruta_relativa: str) -> Path:
    """
    Resuelve una ruta configurable respecto de la raíz del proyecto y devuelve un objeto Path absoluto y normalizado.
    Recibe el nombre de la variable de entorno que puede sobrescribir la ruta y la ruta por defecto, expresada de forma relativa a esa raíz.
    Cabe señalar que una ruta absoluta escrita en la variable de entorno se respeta tal cual, mientras que una relativa se cuelga de la raíz del repositorio.
    """
    valor = _variable(nombre_variable, ruta_relativa)
    candidata = Path(valor)
    if candidata.is_absolute():
        return candidata
    return (RAIZ_PROYECTO / candidata).resolve()


@dataclass(frozen=True)
class ConfiguracionAlmacen:
    """
    Reúne los datos de conexión al almacén analítico en PostgreSQL.
    """

    host: str = field(default_factory=lambda: _variable("ALMACEN_HOST", "postgres"))
    puerto: int = field(default_factory=lambda: int(_variable("ALMACEN_PUERTO", "5432")))
    base: str = field(default_factory=lambda: _variable("ALMACEN_BASE", "analitica"))
    usuario: str = field(default_factory=lambda: _variable("ALMACEN_USUARIO", "analitica"))
    contrasena: str = field(default_factory=lambda: _variable("ALMACEN_CONTRASENA", "analitica"))
    esquema_crudo: str = field(default_factory=lambda: _variable("ALMACEN_ESQUEMA_CRUDO", "crudo"))

    def cadena_conexion(self) -> str:
        """
        Arma la URL de conexión que entiende SQLAlchemy.
        Devuelve una cadena con el formato postgresql+psycopg2://usuario:clave@host:puerto/base.
        """
        return (
            f"postgresql+psycopg2://{self.usuario}:{self.contrasena}"
            f"@{self.host}:{self.puerto}/{self.base}"
        )


@dataclass(frozen=True)
class ConfiguracionMetricas:
    """
    Reúne los parámetros que gobiernan la publicación de métricas hacia Prometheus.
    """

    # Cuando esta dirección queda vacía, el pipeline se limita a escribir las métricas en el log.
    # De ese modo la corrida funciona sin necesidad de levantar la pila de observabilidad.
    url_pushgateway: str = field(
        default_factory=lambda: _variable("PUSHGATEWAY_URL", "http://pushgateway:9091")
    )
    trabajo: str = field(default_factory=lambda: _variable("METRICAS_TRABAJO", "pipeline_ventas"))
    habilitado: bool = field(
        default_factory=lambda: _variable("METRICAS_HABILITADAS", "true").lower() == "true"
    )
    tiempo_espera_segundos: int = field(
        default_factory=lambda: int(_variable("METRICAS_TIEMPO_ESPERA", "5"))
    )


@dataclass(frozen=True)
class ConfiguracionPipeline:
    """
    Agrupa las rutas y los parámetros de negocio del pipeline.
    """

    # A continuación se declaran las rutas del sistema de archivos que el pipeline utiliza.
    directorio_datos: Path = field(default_factory=lambda: _ruta("DIR_DATOS", "datos"))
    directorio_crudos: Path = field(default_factory=lambda: _ruta("DIR_CRUDOS", "datos/crudos"))
    directorio_ejemplos: Path = field(
        default_factory=lambda: _ruta("DIR_EJEMPLOS", "datos/ejemplos")
    )
    directorio_salida: Path = field(default_factory=lambda: _ruta("DIR_SALIDA", "salida"))

    # El archivo de entrada se nombra aparte del directorio que lo contiene, de manera que cambiar de conjunto de datos no obligue a rescribir la ruta completa.
    archivo_entrada: str = field(
        default_factory=lambda: _variable("ARCHIVO_ENTRADA", "ventas_minoristas.csv")
    )

    # El tamaño de lote determina cuántas filas lee y convierte la ingesta por vez.
    # Bajarlo reduce el pico de memoria a costa de algo de velocidad, motivo por el cual es la primera palanca a mover cuando el pipeline corre en un entorno con memoria acotada.
    tamanio_lote_ingesta: int = field(
        default_factory=lambda: int(_variable("TAMANIO_LOTE_INGESTA", "200000"))
    )

    # Los tres parámetros que siguen definen qué se considera un registro válido desde el punto de vista del negocio.
    cantidad_minima: int = field(default_factory=lambda: int(_variable("CANTIDAD_MINIMA", "1")))
    precio_minimo: float = field(default_factory=lambda: float(_variable("PRECIO_MINIMO", "0.01")))
    precio_maximo: float = field(
        default_factory=lambda: float(_variable("PRECIO_MAXIMO", "50000.0"))
    )

    # El umbral de tolerancia fija cuánto rechazo se admite antes de dar la corrida por inválida.
    # En caso de que el porcentaje de filas rechazadas lo supere, el pipeline falla en lugar de publicar un resultado poco confiable.
    porcentaje_rechazo_maximo: float = field(
        default_factory=lambda: float(_variable("PORCENTAJE_RECHAZO_MAXIMO", "15.0"))
    )

    # Los dos parámetros siguientes gobiernan el trabajo distribuido que se ejecuta sobre Spark.
    maestro_spark: str = field(default_factory=lambda: _variable("SPARK_MASTER_URL", "local[*]"))
    particiones_barajado: int = field(
        default_factory=lambda: int(_variable("SPARK_PARTICIONES_BARAJADO", "8"))
    )

    almacen: ConfiguracionAlmacen = field(default_factory=ConfiguracionAlmacen)
    metricas: ConfiguracionMetricas = field(default_factory=ConfiguracionMetricas)

    @property
    def ruta_entrada(self) -> Path:
        """
        Devuelve la ruta completa del archivo crudo que consume la ingesta.
        """
        return self.directorio_crudos / self.archivo_entrada

    @property
    def ruta_muestra(self) -> Path:
        """
        Devuelve la ruta de la muestra versionada en el repositorio, que sirve de respaldo cuando el histórico completo no está descargado.
        """
        return self.directorio_ejemplos / "ventas_minoristas_muestra.csv"

    def resolver_entrada(self) -> Path:
        """
        Elige qué archivo va a consumir la ingesta y devuelve la ruta del que corresponda leer.
        El histórico completo alojado en datos/crudos tiene prioridad, puesto que es el que refleja el volumen real.
        En caso de que ese archivo no esté presente, la elección cae en la muestra versionada en el repositorio, de modo que quien recién clona el proyecto pueda correr el pipeline completo sin descargar nada.
        """
        if self.ruta_entrada.exists():
            return self.ruta_entrada
        return self.ruta_muestra

    @property
    def ruta_detalle_limpio(self) -> Path:
        """
        Devuelve la carpeta Parquet donde queda el detalle de transacciones ya validado.
        """
        return self.directorio_salida / "detalle_ventas"

    @property
    def ruta_agregado(self) -> Path:
        """
        Devuelve la carpeta Parquet donde queda el agregado por fecha y producto.
        """
        return self.directorio_salida / "ingresos_por_producto_fecha"

    @property
    def ruta_agregado_csv(self) -> Path:
        """
        Devuelve la ruta de la copia del agregado en formato CSV, pensada para abrirla en una planilla de cálculo.
        """
        return self.directorio_salida / "ingresos_por_producto_fecha.csv"

    @property
    def ruta_cuarentena(self) -> Path:
        """
        Devuelve la carpeta donde se guardan las filas que no pasaron las validaciones.
        """
        return self.directorio_salida / "cuarentena"

    @property
    def ruta_reportes(self) -> Path:
        """
        Devuelve la carpeta que reúne los reportes de calidad en formato JSON.
        """
        return self.directorio_salida / "reportes"

    @property
    def ruta_spark(self) -> Path:
        """
        Devuelve la carpeta que reúne los resultados del trabajo distribuido de Spark.
        """
        return self.directorio_salida / "analitica_spark"

    def preparar_directorios(self) -> None:
        """
        Crea las carpetas de trabajo que todavía no existan.
        La invocación ocurre al inicio de cada corrida, con el fin de que el pipeline funcione en una máquina recién clonada sin pasos manuales previos.
        """
        for carpeta in (
            self.directorio_crudos,
            self.directorio_ejemplos,
            self.directorio_salida,
            self.ruta_cuarentena,
            self.ruta_reportes,
        ):
            carpeta.mkdir(parents=True, exist_ok=True)


# El mapeo describe el esquema esperado del archivo crudo.
# Al respecto, la clave es el nombre original de la columna en el conjunto de datos de origen y el valor es el nombre en español que usa el pipeline de acá en adelante.
MAPEO_COLUMNAS: dict[str, str] = {
    "Invoice": "factura",
    "InvoiceNo": "factura",
    "StockCode": "producto_id",
    "Description": "descripcion",
    "Quantity": "cantidad",
    "InvoiceDate": "fecha_hora",
    "Price": "precio_unitario",
    "UnitPrice": "precio_unitario",
    "Customer ID": "cliente_id",
    "CustomerID": "cliente_id",
    "Country": "pais",
}

# Las columnas que siguen son las mínimas que debe traer el archivo para que la ingesta continúe.
COLUMNAS_OBLIGATORIAS: tuple[str, ...] = (
    "factura",
    "producto_id",
    "cantidad",
    "fecha_hora",
    "precio_unitario",
)

# En las columnas que siguen, un valor nulo invalida el registro completo.
COLUMNAS_SIN_NULOS: tuple[str, ...] = (
    "producto_id",
    "cantidad",
    "fecha_hora",
    "precio_unitario",
)


def obtener_configuracion() -> ConfiguracionPipeline:
    """
    Construye la configuración leyendo el entorno en el momento de la llamada y devuelve una instancia de ConfiguracionPipeline lista para usar.
    Cabe señalar que se evita a propósito una instancia global de módulo, dado que construirla en cada llamada permite que las pruebas alteren las variables de entorno con monkeypatch y obtengan una configuración distinta sin reiniciar el intérprete.
    """
    return ConfiguracionPipeline()
