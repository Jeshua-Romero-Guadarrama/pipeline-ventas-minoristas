"""
Carga de los resultados del pipeline en el almacén analítico.
Los archivos Parquet resuelven la persistencia, si bien un analista que quiere cruzar las ventas con otra tabla necesita SQL.
Por ello el pipeline también deja los resultados en PostgreSQL, que después es el motor sobre el que trabaja dbt para construir las capas de modelado.
La estrategia de carga es de reemplazo completo por tabla, puesto que con el volumen de este proyecto resulta la opción más simple y la que menos formas tiene de dejar datos a medias.
Ahora bien, cuando el volumen crezca el paso siguiente será cargar por partición de fecha, y el módulo está armado para que ese cambio quede contenido en una sola función.
"""

from __future__ import annotations

import csv
from io import StringIO
from typing import Any

import pandas as pd
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from trabajos.configuracion import ConfiguracionAlmacen
from trabajos.registro import obtener_registrador

registrador = obtener_registrador(__name__)


class ErrorDeCarga(Exception):
    """
    Señala que la escritura en el almacén analítico no se pudo completar.
    """


def _insertar_con_copy(tabla: Any, conexion: Any, columnas: list[str], datos: Any) -> None:
    """
    Inserta un lote de filas mediante el comando COPY de PostgreSQL.
    Recibe el objeto que describe el nombre y el esquema de destino, la conexión activa de SQLAlchemy, los nombres de las columnas del lote y un iterable de tuplas con las filas.
    La función reemplaza el método de inserción por defecto de pandas, y la diferencia de rendimiento no es menor.
    Al respecto, una sentencia INSERT obliga al motor a analizar y planificar cada lote, mientras que COPY escribe directamente sobre la tabla (con el millón de filas de este proyecto la carga pasa de varios minutos a unos pocos segundos).
    La firma la impone pandas, que llama a esta función una vez por lote siempre que se la pase como parámetro method de to_sql.
    """
    conexion_cruda = conexion.connection
    with conexion_cruda.cursor() as cursor:
        # El lote se arma como un CSV en memoria, porque es el formato que COPY entiende.
        # Conviene precisar que QUOTE_MINIMAL deja sin comillas los valores que no las necesitan, con lo que reduce bastante el volumen que viaja hacia el motor.
        # Por ejemplo, el importe 38.97 viaja tal cual, mientras que una descripción con coma como "TAZA BLANCA, CHICA" sí queda entrecomillada.
        memoria = StringIO()
        escritor = csv.writer(memoria, quoting=csv.QUOTE_MINIMAL)
        escritor.writerows(datos)
        memoria.seek(0)

        columnas_sql = ", ".join(f'"{columna}"' for columna in columnas)
        destino = (
            f'"{tabla.schema}"."{tabla.name}"' if tabla.schema else f'"{tabla.name}"'
        )
        sentencia = f"COPY {destino} ({columnas_sql}) FROM STDIN WITH CSV"
        cursor.copy_expert(sql=sentencia, file=memoria)


def crear_motor(configuracion: ConfiguracionAlmacen) -> Engine:
    """
    Construye el motor de conexión a PostgreSQL a partir de los datos de conexión al almacén.
    Al respecto, se activa pool_pre_ping para que una conexión que quedó colgada durante una espera larga se detecte y se reemplace antes de usarla.
    Sin esa comprobación, la primera consulta posterior a un rato de inactividad falla sin motivo aparente.
    Devuelve un motor de SQLAlchemy listo para usar.
    """
    return create_engine(
        configuracion.cadena_conexion(),
        pool_pre_ping=True,
        pool_recycle=1800,
        future=False,
    )


def verificar_conexion(motor: Engine) -> bool:
    """
    Comprueba que el almacén responde antes de intentar cargar datos en él.
    Recibe el motor de SQLAlchemy que corresponde probar y devuelve True cuando la base contesta la consulta de prueba, o bien False en cualquier otro caso.
    Conviene precisar que la falla no se propaga, en razón de que quien llama decide si continuar sin almacén o detener la corrida.
    """
    try:
        with motor.connect() as conexion:
            conexion.execute(text("SELECT 1"))
        return True
    except Exception as error:  # noqa: BLE001
        registrador.warning(
            "El almacén analítico no respondió", extra={"detalle": str(error)}
        )
        return False


def asegurar_esquema(motor: Engine, esquema: str) -> None:
    """
    Crea el esquema de destino en caso de que todavía no exista.
    Recibe el motor conectado al almacén y el nombre del esquema.
    De ese modo, una base recién levantada queda lista para recibir las tablas sin ningún paso manual previo.
    Lanza ErrorDeCarga siempre que la sentencia no se pueda ejecutar.
    """
    try:
        with motor.begin() as conexion:
            conexion.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{esquema}"'))
        registrador.info("Esquema disponible en el almacén", extra={"esquema": esquema})
    except Exception as error:  # noqa: BLE001
        raise ErrorDeCarga(
            f"No se pudo crear el esquema {esquema} en el almacén. "
            "Conviene revisar que el usuario configurado tenga permiso de creación sobre la base. "
            f"Detalle del motor: {error}"
        ) from error


def _columnas_existentes(motor: Engine, nombre_tabla: str, esquema: str) -> list[str] | None:
    """
    Devuelve los nombres de las columnas de una tabla del almacén, o bien None cuando esa tabla todavía no existe.
    Recibe el motor conectado al almacén, el nombre de la tabla y el esquema donde buscarla.
    Cabe señalar que la distinción entre lista vacía y None importa, dado que quien llama decide con ella si corresponde crear la tabla, vaciarla o recrearla.
    """
    inspector = inspect(motor)
    if not inspector.has_table(nombre_tabla, schema=esquema):
        return None
    return [columna["name"] for columna in inspector.get_columns(nombre_tabla, schema=esquema)]


def cargar_tabla(
    datos: pd.DataFrame,
    nombre_tabla: str,
    motor: Engine,
    esquema: str,
    tamanio_lote: int = 50_000,
) -> int:
    """
    Reemplaza por completo el contenido de una tabla del almacén y devuelve la cantidad de filas escritas.
    Recibe los datos a cargar, el nombre de destino dentro del esquema, el motor conectado al almacén, el esquema donde vive la tabla y el número de filas por lote enviado con COPY.
    La forma obvia de resolverlo sería borrar la tabla y volver a crearla, que es lo que hace pandas por defecto, si bien acá no sirve y el motivo resulta importante.
    Al respecto, los modelos de dbt se construyen sobre estas tablas y una vista de PostgreSQL queda ligada a la tabla que consulta, de manera que al intentar borrarla el motor se niega porque hay objetos que dependen de ella.
    El borrado en cascada sería una salida posible, si bien destruiría las vistas y dejaría el almacén a medias hasta la siguiente construcción de dbt.
    La solución correcta consiste en vaciar la tabla en lugar de borrarla, puesto que así el objeto sobrevive, las vistas que dependen de él siguen siendo válidas y el contenido se reemplaza igual.
    Adicionalmente, el vaciado y la carga viajan en la misma transacción, de modo que si la carga falla la tabla conserva sus datos anteriores en vez de quedar vacía.
    Solo hace falta recrear la tabla cuando cambió su estructura de columnas, y en ese caso sí se borra en cascada, porque las vistas construidas sobre la estructura vieja ya no serían válidas de todos modos.
    Por ejemplo, agregar la columna facturas_distintas al agregado obliga a recrear ingresos_por_producto_fecha, motivo por el cual se deja constancia en el registro de que dbt tiene que volver a construir sus modelos.
    En caso de que la tabla llegue vacía, la carga se omite y el resultado es cero.
    Lanza ErrorDeCarga siempre que la escritura falle.
    """
    if datos.empty:
        registrador.warning(
            "Se pidió cargar una tabla vacía, se omite", extra={"tabla": nombre_tabla}
        )
        return 0

    # Los tipos propios de pandas se llevan a tipos que el driver sí sabe enviar.
    # Es decir, los enteros anulables Int64 pasan a punto flotante, las categorías y las cadenas vuelven a texto, y las fechas de tipo date viajan como marca de tiempo.
    preparados = datos.copy()
    for columna in preparados.columns:
        tipo = str(preparados[columna].dtype)
        if tipo == "Int64":
            preparados[columna] = preparados[columna].astype("float64")
        elif tipo in {"string", "category"}:
            preparados[columna] = preparados[columna].astype("object")

    if "fecha" in preparados.columns:
        preparados["fecha"] = pd.to_datetime(preparados["fecha"], errors="coerce")

    destino = f"{esquema}.{nombre_tabla}"
    columnas_actuales = _columnas_existentes(motor, nombre_tabla, esquema)
    columnas_nuevas = list(preparados.columns)

    try:
        if columnas_actuales is None:
            # La tabla no existe todavía, motivo por el cual se crea desde cero y no hay ninguna vista que pueda quedar rota.
            modo = "creacion"
            preparados.to_sql(
                name=nombre_tabla,
                con=motor,
                schema=esquema,
                if_exists="replace",
                index=False,
                chunksize=tamanio_lote,
                method=_insertar_con_copy,
            )
        elif set(columnas_actuales) == set(columnas_nuevas):
            # El caso habitual consiste en vaciar la tabla y recargarla sin tocar el objeto ni las vistas que dependen de él.
            modo = "vaciado_y_carga"
            with motor.begin() as conexion:
                conexion.execute(text(f'TRUNCATE TABLE "{esquema}"."{nombre_tabla}"'))
                preparados.to_sql(
                    name=nombre_tabla,
                    con=conexion,
                    schema=esquema,
                    if_exists="append",
                    index=False,
                    chunksize=tamanio_lote,
                    method=_insertar_con_copy,
                )
        else:
            # Cambió la estructura de columnas, de ahí que haya que recrear la tabla, operación que arrastra consigo las vistas construidas sobre ella.
            modo = "recreacion"
            registrador.warning(
                "La estructura de la tabla cambió, se recrea junto con sus dependencias. "
                "Hay que volver a construir los modelos de dbt.",
                extra={
                    "tabla": destino,
                    "columnas_anteriores": sorted(columnas_actuales),
                    "columnas_nuevas": sorted(columnas_nuevas),
                },
            )
            with motor.begin() as conexion:
                conexion.execute(text(f'DROP TABLE IF EXISTS "{esquema}"."{nombre_tabla}" CASCADE'))
            preparados.to_sql(
                name=nombre_tabla,
                con=motor,
                schema=esquema,
                if_exists="replace",
                index=False,
                chunksize=tamanio_lote,
                method=_insertar_con_copy,
            )
    except Exception as error:  # noqa: BLE001
        raise ErrorDeCarga(
            f"No se pudo cargar la tabla {destino} en el almacén. "
            "Conviene revisar que el almacén siga accesible y que los tipos de las columnas coincidan con los de la tabla de destino. "
            f"Detalle del motor: {error}"
        ) from error

    filas = int(len(preparados))
    registrador.info(
        "Tabla cargada en el almacén",
        extra={"tabla": destino, "filas": filas, "modo": modo},
    )
    return filas


def cargar_resultados(
    detalle: pd.DataFrame,
    agregado: pd.DataFrame,
    resumen_diario: pd.DataFrame,
    configuracion: ConfiguracionAlmacen,
) -> dict[str, int]:
    """
    Carga las tres tablas de salida del pipeline en el almacén analítico.
    Recibe el detalle de transacciones limpias a nivel de línea de factura, el ingreso por fecha y producto, las métricas agregadas por día y los datos de conexión al almacén.
    Devuelve un diccionario con la cantidad de filas cargadas por tabla, que queda vacío en caso de que el almacén no estuviera disponible.
    Al respecto, un almacén caído no rompe la corrida, dado que la función se limita a dejar constancia en el registro y a devolver ese diccionario vacío.
    De ese modo, el pipeline se puede ejecutar en una máquina sin Docker, donde el resultado escrito en Parquet sigue siendo igualmente válido.
    """
    motor = crear_motor(configuracion)

    if not verificar_conexion(motor):
        registrador.warning(
            "Se omite la carga al almacén porque la base no está accesible. "
            "Los resultados en Parquet quedaron escritos igual."
        )
        return {}

    asegurar_esquema(motor, configuracion.esquema_crudo)

    resultados = {
        "detalle_ventas": cargar_tabla(
            detalle, "detalle_ventas", motor, configuracion.esquema_crudo
        ),
        "ingresos_por_producto_fecha": cargar_tabla(
            agregado, "ingresos_por_producto_fecha", motor, configuracion.esquema_crudo
        ),
        "resumen_diario": cargar_tabla(
            resumen_diario, "resumen_diario", motor, configuracion.esquema_crudo
        ),
    }

    registrador.info("Carga al almacén finalizada", extra={"filas_por_tabla": resultados})
    return resultados
