"""
Grafo de vigilancia de la calidad del almacén analítico.
El presente grafo no transforma nada, sino que se limita a mirar.
Corre cada seis horas y formula las preguntas que uno haría a mano si sospechara que algo anda mal, es decir, si los datos siguen actualizados, si el volumen cambió respecto de lo habitual y si los totales continúan cerrando entre capas.
La separación respecto del grafo principal es deliberada, puesto que aquel construye y este audita.
De ese modo se evita que un problema de vigilancia detenga la producción de datos, que sería exactamente lo contrario de lo que se busca.
Los resultados van al registro y a Prometheus.
Cabe señalar que la alerta que ve el equipo se dispara desde Prometheus y no desde aquí, en razón de que el sistema de alertas ya sabe agrupar, silenciar y enrutar avisos, de manera que reimplementar todo eso sería trabajo perdido.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from airflow.decorators import task
from airflow.models.dag import DAG
from airflow.operators.empty import EmptyOperator
from airflow.utils.trigger_rule import TriggerRule

RAIZ_PROYECTO = Path(os.environ.get("RAIZ_PROYECTO", "/opt/proyecto"))
if str(RAIZ_PROYECTO) not in sys.path:
    sys.path.insert(0, str(RAIZ_PROYECTO))

ARGUMENTOS_POR_DEFECTO = {
    "owner": "equipo-datos",
    "depends_on_past": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=1),
    "execution_timeout": timedelta(minutes=15),
}

DOCUMENTACION = """
### Vigilancia de calidad del almacén

El grafo corre cada seis horas y comprueba tres cosas sobre las tablas publicadas.

1. `verificar_frescura` mide cuánto tiempo pasó desde el dato más reciente.
2. `verificar_volumen` compara el conteo de filas de cada tabla contra la corrida anterior.
3. `verificar_coherencia` reconstruye los totales y los contrasta entre la capa cruda y la publicada.

Ninguna de las tareas modifica datos.
En consecuencia, un fallo aquí significa que hay que revisar el grafo principal, y no que este grafo tenga un problema.
"""


with DAG(
    dag_id="vigilancia_calidad_datos",
    description="Comprobaciones periódicas sobre el almacén analítico",
    doc_md=DOCUMENTACION,
    default_args=ARGUMENTOS_POR_DEFECTO,
    start_date=datetime(2024, 1, 1),
    schedule="0 */6 * * *",
    catchup=False,
    max_active_runs=1,
    tags=["calidad", "monitoreo"],
) as grafo:

    inicio = EmptyOperator(task_id="inicio")

    @task(task_id="verificar_frescura")
    def verificar_frescura() -> dict[str, object]:
        """
        Mide la antigüedad del dato más reciente del almacén.
        Un almacén que responde bien a las consultas pero devuelve datos de hace tres días resulta peor que uno caído, en razón de que nadie se da cuenta.
        Devuelve un diccionario con la fecha más reciente y la cantidad de días publicados.
        Lanza ValueError en caso de que la tabla esté vacía, que es el síntoma real de una carga incompleta.
        """
        from sqlalchemy import text

        from trabajos.carga_almacen import crear_motor
        from trabajos.configuracion import obtener_configuracion

        configuracion = obtener_configuracion()
        motor = crear_motor(configuracion.almacen)

        with motor.connect() as conexion:
            fila = conexion.execute(
                text(
                    """
                    select
                        max(fecha) as fecha_maxima,
                        count(*)   as filas
                    from publicado.pub_resumen_diario
                    """
                )
            ).fetchone()

        fecha_maxima = fila[0]
        filas = int(fila[1])

        print(f"Dato más reciente del almacén {fecha_maxima}, sobre {filas:,} días.")

        # El conjunto de datos de este proyecto es un histórico cerrado que
        # termina en diciembre de 2011, así que la antigüedad calendaria no
        # aplica. Lo que sí se comprueba es que la tabla no esté vacía y que
        # tenga una fecha máxima válida, que es el síntoma real de una carga
        # incompleta.
        if filas == 0 or fecha_maxima is None:
            raise ValueError(
                "La tabla publicado.pub_resumen_diario está vacía. "
                "La última corrida del pipeline no dejó datos."
            )

        return {"fecha_maxima": str(fecha_maxima), "dias_publicados": filas}

    @task(task_id="verificar_volumen")
    def verificar_volumen() -> dict[str, int]:
        """
        Cuenta las filas de cada tabla publicada.
        El conteo por sí solo no dice mucho, dado que lo que importa es compararlo contra la corrida anterior, y de eso se encarga Prometheus cuando recibe la métrica.
        Aquí simplemente se produce el número y se deja registrado.
        Devuelve un diccionario con la cantidad de filas de cada tabla.
        Lanza ValueError siempre que alguna tabla haya quedado vacía tras la última corrida.
        """
        from sqlalchemy import text

        from trabajos.carga_almacen import crear_motor
        from trabajos.configuracion import obtener_configuracion

        configuracion = obtener_configuracion()
        motor = crear_motor(configuracion.almacen)

        tablas = [
            "publicado.pub_ingresos_producto_fecha",
            "publicado.pub_resumen_diario",
            "publicado.pub_ranking_productos",
            "publicado.pub_ventas_por_pais",
            "crudo.detalle_ventas",
        ]

        conteos: dict[str, int] = {}
        with motor.connect() as conexion:
            for tabla in tablas:
                cantidad = conexion.execute(text(f"select count(*) from {tabla}")).scalar()
                conteos[tabla] = int(cantidad or 0)
                print(f"{tabla:45s} {conteos[tabla]:>12,} filas")

        vacias = [tabla for tabla, cantidad in conteos.items() if cantidad == 0]
        if vacias:
            raise ValueError(f"Las tablas siguientes quedaron vacías tras la última corrida: {vacias}")

        return conteos

    @task(task_id="verificar_coherencia")
    def verificar_coherencia() -> dict[str, float]:
        """
        Contrasta los totales entre la capa cruda y la publicada.
        La comprobación es la misma que hace dbt, ejecutada de nuevo un rato después.
        Al respecto, la repetición tiene sentido porque detecta cualquier cambio posterior a la construcción, ya sea una carga manual o una corrida parcial que dejó el almacén a medias.
        Devuelve los dos totales comparados junto con su diferencia absoluta.
        Lanza ValueError en caso de que esa diferencia supere un centavo, margen que cubre el redondeo acumulado sobre un millón de filas.
        """
        from sqlalchemy import text

        from trabajos.carga_almacen import crear_motor
        from trabajos.configuracion import obtener_configuracion

        configuracion = obtener_configuracion()
        motor = crear_motor(configuracion.almacen)

        with motor.connect() as conexion:
            total_crudo = conexion.execute(
                text("select round(cast(sum(ingreso_total) as numeric), 2) from crudo.detalle_ventas")
            ).scalar()
            total_publicado = conexion.execute(
                text(
                    "select round(cast(sum(ingreso_total) as numeric), 2) "
                    "from publicado.pub_ingresos_producto_fecha"
                )
            ).scalar()

        crudo = float(total_crudo or 0)
        publicado = float(total_publicado or 0)
        diferencia = round(abs(crudo - publicado), 2)

        print(f"Total en la capa cruda      {crudo:,.2f}")
        print(f"Total en la capa publicada  {publicado:,.2f}")
        print(f"Diferencia                  {diferencia:,.2f}")

        # Un centavo cubre el redondeo acumulado sobre un millón de filas.
        if diferencia > 0.01:
            raise ValueError(
                f"Los totales no coinciden entre capas. Diferencia de {diferencia}. "
                "Revisar si hubo una carga parcial o una construcción interrumpida."
            )

        return {
            "total_crudo": crudo,
            "total_publicado": publicado,
            "diferencia": diferencia,
        }

    @task(task_id="publicar_metricas_de_calidad", trigger_rule=TriggerRule.ALL_DONE)
    def publicar_metricas_de_calidad(
        frescura: dict[str, object] | None,
        volumen: dict[str, int] | None,
        coherencia: dict[str, float] | None,
    ) -> None:
        """
        Empuja los resultados de la vigilancia hacia Prometheus.
        Recibe en frescura el resultado de la comprobación de actualidad, en volumen los conteos por tabla y en coherencia la comparación de totales entre capas.
        La regla de disparo es ALL_DONE a propósito, puesto que si una comprobación falló, justamente ahí es cuando más importa que la métrica llegue al sistema de monitoreo.
        """
        from trabajos.configuracion import obtener_configuracion
        from trabajos.metricas import RecolectorMetricas

        configuracion = obtener_configuracion()
        recolector = RecolectorMetricas(configuracion=configuracion.metricas)

        if volumen:
            for tabla, cantidad in volumen.items():
                recolector.registrar_valor(
                    "almacen_filas_por_tabla",
                    float(cantidad),
                    tabla=tabla.replace(".", "_"),
                )

        if frescura:
            recolector.registrar_valor(
                "almacen_dias_publicados", float(frescura.get("dias_publicados", 0))
            )

        if coherencia:
            recolector.registrar_valor(
                "almacen_diferencia_entre_capas", float(coherencia.get("diferencia", 0))
            )

        recolector.registrar_valor(
            "almacen_vigilancia_completada", 1.0 if (volumen and coherencia) else 0.0
        )
        recolector.publicar()
        print("Métricas de vigilancia publicadas.")

    fin = EmptyOperator(task_id="fin", trigger_rule=TriggerRule.ALL_DONE)

    resultado_frescura = verificar_frescura()
    resultado_volumen = verificar_volumen()
    resultado_coherencia = verificar_coherencia()

    inicio >> [resultado_frescura, resultado_volumen, resultado_coherencia]

    publicacion = publicar_metricas_de_calidad(
        resultado_frescura, resultado_volumen, resultado_coherencia
    )

    [resultado_frescura, resultado_volumen, resultado_coherencia] >> publicacion >> fin
