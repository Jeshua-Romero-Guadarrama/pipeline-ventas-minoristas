"""
Pruebas de integridad de los grafos de Airflow.
Cabe señalar que estas pruebas no ejecutan tareas, sino que se limitan a comprobar que los archivos de grafo están bien formados.
Suena poco, aunque atrapa la falla más frecuente y más molesta del orquestador.
Al respecto, un error de sintaxis o una importación rota hacen que Airflow no cargue el grafo, y lo único que se ve es que el grafo desapareció de la lista sin ninguna explicación visible.
En consecuencia, detectarlo en la batería de pruebas evita descubrirlo recién cuando la corrida programada no arranca.
En caso de que Airflow no esté instalado en el entorno, situación habitual cuando alguien corre las pruebas fuera del contenedor, el archivo entero se omite.
Dicha omisión resulta preferible antes que convertir a Airflow en una dependencia obligatoria del desarrollo local.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Airflow solo está instalado dentro de la imagen del orquestador, motivo por el cual la importación se intenta y, si falla, el archivo completo se omite en lugar de dar error.
airflow_models = pytest.importorskip(
    "airflow.models", reason="Airflow no está instalado en este entorno"
)

RAIZ = Path(__file__).resolve().parent.parent
CARPETA_DAGS = RAIZ / "orquestacion" / "dags"

# Los grafos leen esta variable para ubicar la raíz del proyecto.
# Al respecto, dentro del contenedor apunta a /opt/proyecto, mientras que acá se la hace apuntar al repositorio.
os.environ.setdefault("RAIZ_PROYECTO", str(RAIZ))


@pytest.fixture(scope="module")
def bolsa_de_grafos():
    """
    Carga todos los archivos de grafo de la carpeta de Airflow.
    Lo que se devuelve es la bolsa de grafos que arma Airflow al leer esa carpeta, que es el objeto sobre el que trabajan todas las pruebas del archivo.
    El alcance es de módulo porque la lectura se hace una sola vez y ninguna prueba la modifica.
    """
    return airflow_models.DagBag(dag_folder=str(CARPETA_DAGS), include_examples=False)


def test_no_hay_errores_de_importacion(bolsa_de_grafos) -> None:
    """
    Comprueba que ningún archivo de grafo tiene errores de sintaxis ni de importación.
    Al respecto, constituye la prueba más importante del archivo, puesto que un fallo acá significa que el grafo no va a aparecer en Airflow.
    """
    assert not bolsa_de_grafos.import_errors, (
        f"Hay grafos que no se pudieron importar: {bolsa_de_grafos.import_errors}"
    )


def test_se_cargaron_los_dos_grafos(bolsa_de_grafos) -> None:
    """
    Comprueba que la carpeta aporta los dos grafos del proyecto, es decir, el principal de ventas y el de vigilancia de calidad.
    """
    identificadores = set(bolsa_de_grafos.dag_ids)

    assert "ventas_minoristas_diario" in identificadores
    assert "vigilancia_calidad_datos" in identificadores


def test_el_grafo_principal_tiene_todas_sus_tareas(bolsa_de_grafos) -> None:
    """
    Comprueba que el grafo principal conserva las diez tareas que componen el pipeline de punta a punta.
    Al respecto, si alguien renombra una tarea sin actualizar las dependencias, el grafo se carga igual y el faltante solo se nota cuando la corrida se detiene a medias.
    """
    grafo = bolsa_de_grafos.get_dag("ventas_minoristas_diario")
    tareas = set(grafo.task_ids)

    esperadas = {
        "inicio",
        "preparacion.verificar_archivo_de_entrada",
        "preparacion.verificar_almacen",
        "procesar_ventas",
        "modelado_dbt.instalar_dependencias",
        "modelado_dbt.construir_modelos",
        "modelado_dbt.probar_modelos",
        "analisis_distribuido",
        "resumen_de_la_corrida",
        "fin",
    }

    faltantes = esperadas - tareas
    assert not faltantes, f"Al grafo principal le faltan tareas: {faltantes}"


def test_el_grafo_principal_no_tiene_ciclos(bolsa_de_grafos) -> None:
    """
    Comprueba que las dependencias del grafo principal no forman ningún ciclo.
    Puesto que un ciclo dejaría tareas esperándose entre sí, la corrida nunca llegaría a terminar.
    """
    grafo = bolsa_de_grafos.get_dag("ventas_minoristas_diario")
    grafo.validate()


def test_la_validacion_precede_al_procesamiento(bolsa_de_grafos) -> None:
    """
    Comprueba que las verificaciones previas corren antes de gastar tiempo de cómputo.
    Al respecto, si este orden se invirtiera, un archivo faltante se descubriría después de varios minutos de procesamiento en lugar de en dos segundos.
    """
    grafo = bolsa_de_grafos.get_dag("ventas_minoristas_diario")
    procesamiento = grafo.get_task("procesar_ventas")

    anteriores = {tarea.task_id for tarea in procesamiento.upstream_list}
    assert any("preparacion" in identificador for identificador in anteriores)


def test_dbt_y_spark_dependen_del_procesamiento(bolsa_de_grafos) -> None:
    """
    Comprueba que el modelado con dbt y el análisis distribuido con Spark esperan a que termine el procesamiento.
    Dado que ambas etapas leen lo que produce esa tarea, arrancar antes las dejaría trabajando sobre los datos de la corrida anterior.
    """
    grafo = bolsa_de_grafos.get_dag("ventas_minoristas_diario")

    spark = grafo.get_task("analisis_distribuido")
    anteriores_spark = {tarea.task_id for tarea in spark.upstream_list}
    assert "procesar_ventas" in anteriores_spark

    dbt = grafo.get_task("modelado_dbt.instalar_dependencias")
    anteriores_dbt = {tarea.task_id for tarea in dbt.upstream_list}
    assert "procesar_ventas" in anteriores_dbt


def test_los_modelos_de_dbt_se_prueban_despues_de_construirse(bolsa_de_grafos) -> None:
    """
    Comprueba que las pruebas de dbt corren después de la construcción de los modelos.
    En razón de que las pruebas consultan tablas que la construcción todavía no creó, invertir el orden produciría un fallo sin ninguna relación con la calidad de los datos.
    """
    grafo = bolsa_de_grafos.get_dag("ventas_minoristas_diario")
    prueba = grafo.get_task("modelado_dbt.probar_modelos")

    anteriores = {tarea.task_id for tarea in prueba.upstream_list}
    assert "modelado_dbt.construir_modelos" in anteriores


def test_todas_las_tareas_tienen_reintentos_configurados(bolsa_de_grafos) -> None:
    """
    Comprueba que todas las tareas de todos los grafos tienen una cantidad de reintentos válida.
    Al respecto, un fallo transitorio (una base que todavía arranca o una descarga que se corta) no debería obligar a nadie a intervenir a mano.
    """
    for identificador in bolsa_de_grafos.dag_ids:
        grafo = bolsa_de_grafos.get_dag(identificador)
        for tarea in grafo.tasks:
            assert tarea.retries >= 0, (
                f"La tarea {tarea.task_id} del grafo {identificador} "
                "tiene una configuración de reintentos inválida"
            )


def test_los_grafos_tienen_documentacion(bolsa_de_grafos) -> None:
    """
    Comprueba que cada grafo trae documentación extensa y descripción breve.
    De ese modo, quien abra el grafo en la interfaz de Airflow entiende qué hace sin tener que leer el código fuente.
    """
    for identificador in bolsa_de_grafos.dag_ids:
        grafo = bolsa_de_grafos.get_dag(identificador)
        assert grafo.doc_md, f"El grafo {identificador} no tiene documentación"
        assert grafo.description, f"El grafo {identificador} no tiene descripción"


def test_los_grafos_tienen_etiquetas(bolsa_de_grafos) -> None:
    """
    Comprueba que cada grafo lleva al menos una etiqueta.
    Puesto que las etiquetas son el único filtro cómodo de la interfaz, un grafo sin ellas se vuelve difícil de encontrar en cuanto la instalación crece.
    """
    for identificador in bolsa_de_grafos.dag_ids:
        grafo = bolsa_de_grafos.get_dag(identificador)
        assert grafo.tags, f"El grafo {identificador} no tiene etiquetas"


def test_ningun_grafo_recupera_corridas_pasadas(bolsa_de_grafos) -> None:
    """
    Comprueba que ningún grafo tiene activada la recuperación de corridas pasadas.
    Dado que el pipeline procesa el histórico completo en cada corrida, recuperar los días atrasados solo repetiría el mismo trabajo.
    En caso de que alguien activara esa recuperación por descuido, al despausar el grafo se dispararían cientos de corridas idénticas de golpe.
    """
    for identificador in bolsa_de_grafos.dag_ids:
        grafo = bolsa_de_grafos.get_dag(identificador)
        assert not grafo.catchup, (
            f"El grafo {identificador} tiene la recuperación activada"
        )


def test_los_grafos_limitan_las_corridas_simultaneas(bolsa_de_grafos) -> None:
    """
    Comprueba que el grafo principal admite una sola corrida activa a la vez.
    En razón de que todas las corridas escriben sobre las mismas rutas de salida, dos simultáneas se pisarían y dejarían un resultado imposible de interpretar.
    """
    grafo = bolsa_de_grafos.get_dag("ventas_minoristas_diario")
    assert grafo.max_active_runs == 1
