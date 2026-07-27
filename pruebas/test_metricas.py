"""
Pruebas de la capa de métricas.
El punto más importante que se verifica es que un fallo al publicar métricas nunca interrumpe la corrida.
Dicho de otro modo, una caída del Pushgateway no puede invalidar datos que se calcularon bien.
"""

from __future__ import annotations

import time

import pytest

from trabajos.configuracion import ConfiguracionMetricas
from trabajos.metricas import RecolectorMetricas, medir_etapa


def _valor(recolector: RecolectorMetricas, nombre: str, **etiquetas: str) -> float | None:
    """
    Busca el valor de una métrica dentro del registro del recolector.
    Recibe el recolector donde mirar, el nombre de la métrica y las etiquetas que identifican la serie concreta.
    Devuelve el valor encontrado, o bien None en caso de que esa serie todavía no exista.
    Cabe señalar que se pasa None en lugar de un diccionario vacío cuando no hay etiquetas, porque así lo exige la biblioteca de Prometheus para las series sin dimensiones.
    """
    return recolector.registro.get_sample_value(nombre, etiquetas or None)


@pytest.fixture
def recolector() -> RecolectorMetricas:
    """
    Devuelve un recolector con la publicación desactivada.
    De ese modo, las pruebas ejercitan el registro de métricas sin necesidad de tener un Pushgateway levantado.
    """
    return RecolectorMetricas(
        configuracion=ConfiguracionMetricas(
            url_pushgateway="", trabajo="pruebas", habilitado=False, tiempo_espera_segundos=1
        )
    )


def test_registra_la_cantidad_de_filas_por_etapa(recolector: RecolectorMetricas) -> None:
    """
    Comprueba que cada etapa deja su conteo de filas en una serie propia.
    Al respecto, la ingesta registra 1000 filas y la validación 950, valores que quedan separados por la etiqueta de etapa y no se mezclan entre sí.
    """
    recolector.registrar_filas("ingesta", 1000)
    recolector.registrar_filas("validacion", 950)

    assert _valor(recolector, "pipeline_ventas_filas_procesadas", etapa="ingesta") == 1000
    assert _valor(recolector, "pipeline_ventas_filas_procesadas", etapa="validacion") == 950


def test_los_rechazos_se_acumulan_por_regla(recolector: RecolectorMetricas) -> None:
    """
    Comprueba que el contador de rechazos acumula cuando la misma regla se registra dos veces.
    Al respecto, se registran 20 y luego 5 rechazos por cantidad_minima, de manera que la serie tiene que quedar en 25 y no en 5.
    """
    recolector.registrar_rechazos("cantidad_minima", 20)
    recolector.registrar_rechazos("cantidad_minima", 5)

    assert (
        _valor(recolector, "pipeline_ventas_filas_rechazadas_total", regla="cantidad_minima") == 25
    )


def test_registra_una_metrica_de_negocio_sin_etiquetas(recolector: RecolectorMetricas) -> None:
    """
    Comprueba que un valor global de negocio se publica como medidor simple, sin ninguna etiqueta.
    Puesto que el ingreso total no se desglosa por etapa ni por regla, agregarle dimensiones solo complicaría las consultas del tablero.
    """
    recolector.registrar_valor("pipeline_ventas_ingreso_total", 20_476_082.15)

    assert _valor(recolector, "pipeline_ventas_ingreso_total") == pytest.approx(20_476_082.15)


def test_marca_el_resultado_de_la_corrida(recolector: RecolectorMetricas) -> None:
    """
    Comprueba que una corrida exitosa deja el indicador en 1 y además una marca de tiempo posterior a cero.
    Al respecto, esa marca es la que permite alertar cuando pasó demasiado tiempo desde el último éxito, cosa que el indicador por sí solo no distingue.
    """
    recolector.registrar_resultado(exitoso=True)

    assert _valor(recolector, "pipeline_ventas_ejecucion_exitosa") == 1
    marca = _valor(recolector, "pipeline_ventas_ultima_ejecucion_exitosa_timestamp")
    assert marca is not None and marca > 0


def test_una_corrida_fallida_deja_el_indicador_en_cero(recolector: RecolectorMetricas) -> None:
    """
    Comprueba que una corrida fallida deja el indicador en 0 y no toca la marca del último éxito.
    Al respecto, sobre esa métrica se arma la alerta de pipeline caído, motivo por el cual una corrida fallida no debe sobrescribir la fecha del último resultado bueno.
    """
    recolector.registrar_resultado(exitoso=False)

    assert _valor(recolector, "pipeline_ventas_ejecucion_exitosa") == 0
    assert _valor(recolector, "pipeline_ventas_ultima_ejecucion_exitosa_timestamp") is None


def test_el_medidor_de_etapas_registra_la_duracion(recolector: RecolectorMetricas) -> None:
    """
    Comprueba que el administrador de contexto mide la duración del bloque que envuelve.
    Al respecto, el bloque duerme 0.05 segundos, de modo que la duración registrada tiene que ser al menos ese valor.
    """
    with medir_etapa(recolector, "prueba"):
        time.sleep(0.05)

    duracion = _valor(recolector, "pipeline_ventas_duracion_segundos", etapa="prueba")
    assert duracion is not None and duracion >= 0.05


def test_la_duracion_se_registra_aunque_el_bloque_falle(recolector: RecolectorMetricas) -> None:
    """
    Comprueba que la duración se registra aunque el bloque medido levante una excepción.
    Al respecto, saber cuánto tardó una etapa que falló ayuda a distinguir un cuelgue por espera de un fallo inmediato de configuración.
    """
    with pytest.raises(ValueError), medir_etapa(recolector, "etapa_rota"):
        raise ValueError("falla simulada")

    assert _valor(recolector, "pipeline_ventas_duracion_segundos", etapa="etapa_rota") is not None


def test_no_publica_cuando_esta_desactivado(recolector: RecolectorMetricas) -> None:
    """
    Comprueba que con la publicación apagada el recolector registra pero no intenta enviar nada.
    De ese modo, el pipeline se puede correr en una máquina de desarrollo sin Prometheus levantado.
    """
    recolector.registrar_filas("ingesta", 10)

    assert recolector.publicar() is False


def test_un_destino_inalcanzable_no_rompe_la_corrida() -> None:
    """
    Comprueba que un destino inalcanzable no rompe la corrida.
    Al respecto, se apunta el recolector al puerto 9 de la máquina local, donde con certeza no escucha nadie, y la publicación devuelve False en lugar de propagar el error de red.
    En consecuencia, el fallo queda como una advertencia en el registro y los datos ya calculados siguen siendo válidos.
    """
    recolector = RecolectorMetricas(
        configuracion=ConfiguracionMetricas(
            url_pushgateway="http://127.0.0.1:9",
            trabajo="pruebas",
            habilitado=True,
            tiempo_espera_segundos=1,
        )
    )
    recolector.registrar_filas("ingesta", 10)

    assert recolector.publicar() is False
