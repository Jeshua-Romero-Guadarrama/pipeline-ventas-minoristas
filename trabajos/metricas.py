"""
Publicación de las métricas del pipeline hacia Prometheus.
El pipeline es un proceso por lotes y no un servicio web, de modo que no puede exponer un punto de acceso que Prometheus consulte, dado que para cuando llegara el raspado el proceso ya habría terminado.
La solución habitual para este caso es el Pushgateway, un intermediario donde el trabajo empuja sus métricas al terminar y desde el cual Prometheus las lee después.
Todo el módulo está pensado para degradarse sin romper nada, así que si el Pushgateway no está disponible las métricas se escriben igual en el log y la corrida sigue adelante.
Conviene precisar que un problema de observabilidad nunca debería tirar abajo un pipeline que produjo datos correctos.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from prometheus_client import CollectorRegistry, Counter, Gauge, push_to_gateway

from trabajos.configuracion import ConfiguracionMetricas
from trabajos.registro import obtener_registrador

registrador = obtener_registrador(__name__)


@dataclass
class RecolectorMetricas:
    """
    Acumula las métricas de una corrida y las envía cuando esta termina.
    Recibe en configuracion los parámetros de conexión y de activación, y guarda en registro el conjunto aislado de métricas que pertenece a esa corrida.
    Conviene precisar que se emplea un registro propio en lugar del global de prometheus_client, para que cada corrida empuje únicamente sus valores y las pruebas no arrastren estado de un caso al siguiente.
    """

    configuracion: ConfiguracionMetricas
    registro: CollectorRegistry = field(default_factory=CollectorRegistry)
    _medidores: dict[str, Gauge] = field(default_factory=dict, init=False, repr=False)
    _contadores: dict[str, Counter] = field(default_factory=dict, init=False, repr=False)

    def _obtener_medidor(self, nombre: str, descripcion: str, etiquetas: tuple[str, ...]) -> Gauge:
        """
        Crea un medidor la primera vez que se lo necesita y en las llamadas siguientes reutiliza el que ya existe.
        Recibe el nombre de la métrica en Prometheus, el texto de ayuda que la acompaña y los nombres de las etiquetas que llevará la serie.
        Devuelve el objeto Gauge asociado a ese nombre.
        """
        if nombre not in self._medidores:
            self._medidores[nombre] = Gauge(
                nombre, descripcion, list(etiquetas), registry=self.registro
            )
        return self._medidores[nombre]

    def _obtener_contador(
        self, nombre: str, descripcion: str, etiquetas: tuple[str, ...]
    ) -> Counter:
        """
        Crea un contador la primera vez que se lo necesita y en las llamadas siguientes reutiliza el que ya existe.
        Recibe el nombre de la métrica en Prometheus, el texto de ayuda que la acompaña y los nombres de las etiquetas que llevará la serie.
        Devuelve el objeto Counter asociado a ese nombre.
        """
        if nombre not in self._contadores:
            self._contadores[nombre] = Counter(
                nombre, descripcion, list(etiquetas), registry=self.registro
            )
        return self._contadores[nombre]

    def registrar_filas(self, etapa: str, cantidad: int) -> None:
        """
        Anota cuántas filas dejó una etapa del pipeline.
        Recibe el nombre de la etapa (por ejemplo "ingesta" o "agregacion") y la cantidad de filas resultante.
        Comparar esta métrica entre etapas muestra de un vistazo dónde se pierden registros, que suele ser la primera pregunta cuando un número del tablero no cierra.
        """
        medidor = self._obtener_medidor(
            "pipeline_ventas_filas_procesadas",
            "Cantidad de filas al terminar cada etapa del pipeline",
            ("etapa",),
        )
        medidor.labels(etapa=etapa).set(cantidad)
        registrador.info("Filas registradas en la etapa", extra={"etapa": etapa, "filas": cantidad})

    def registrar_duracion(self, etapa: str, segundos: float) -> None:
        """
        Anota cuánto tardó una etapa.
        Recibe el nombre de la etapa medida y su duración expresada en segundos.
        """
        medidor = self._obtener_medidor(
            "pipeline_ventas_duracion_segundos",
            "Duración en segundos de cada etapa del pipeline",
            ("etapa",),
        )
        medidor.labels(etapa=etapa).set(segundos)

    def registrar_rechazos(self, regla: str, cantidad: int) -> None:
        """
        Anota cuántas filas rechazó una regla de calidad concreta.
        Recibe el identificador de la regla que provocó el rechazo y la cantidad de filas afectadas.
        """
        contador = self._obtener_contador(
            "pipeline_ventas_filas_rechazadas_total",
            "Filas descartadas por cada regla de validación",
            ("regla",),
        )
        contador.labels(regla=regla).inc(cantidad)

    def registrar_valor(self, nombre: str, valor: float, **etiquetas: str) -> None:
        """
        Publica una métrica de negocio arbitraria.
        Recibe el nombre completo de la métrica en Prometheus, el valor numérico que se va a publicar y, de manera opcional, pares de clave y valor que se convierten en etiquetas de la serie.
        """
        medidor = self._obtener_medidor(nombre, f"Métrica de negocio {nombre}", tuple(etiquetas))
        if etiquetas:
            medidor.labels(**etiquetas).set(valor)
        else:
            medidor.set(valor)

    def registrar_resultado(self, exitoso: bool) -> None:
        """
        Marca si la corrida terminó bien y, cuando así fue, deja constancia del momento de esa última corrida exitosa.
        Recibe en exitoso el valor True siempre que el pipeline haya completado todas sus etapas.
        La marca de tiempo permite alertar por datos desactualizados, que es el síntoma más frecuente de un pipeline que dejó de correr sin que nadie se diera cuenta.
        """
        self._obtener_medidor(
            "pipeline_ventas_ejecucion_exitosa",
            "Vale 1 si la última corrida terminó sin errores y 0 si falló",
            (),
        ).set(1 if exitoso else 0)

        if exitoso:
            self._obtener_medidor(
                "pipeline_ventas_ultima_ejecucion_exitosa_timestamp",
                "Marca de tiempo Unix de la última corrida exitosa",
                (),
            ).set(time.time())

    def publicar(self) -> bool:
        """
        Empuja todas las métricas acumuladas al Pushgateway.
        Devuelve True si el envío llegó a destino y False si se omitió por configuración o si el intento falló.
        """
        if not self.configuracion.habilitado or not self.configuracion.url_pushgateway:
            registrador.info("Publicación de métricas desactivada, se omite el envío")
            return False

        try:
            push_to_gateway(
                gateway=self.configuracion.url_pushgateway,
                job=self.configuracion.trabajo,
                registry=self.registro,
                timeout=self.configuracion.tiempo_espera_segundos,
            )
            registrador.info(
                "Métricas publicadas correctamente",
                extra={"destino": self.configuracion.url_pushgateway},
            )
            return True
        except Exception as error:  # noqa: BLE001
            # La captura de cualquier excepción es deliberada, dado que la observabilidad es un apoyo y no puede hacer fallar una corrida que ya produjo datos correctos.
            registrador.warning(
                "No se pudieron publicar las métricas, la corrida continúa",
                extra={"detalle": str(error), "destino": self.configuracion.url_pushgateway},
            )
            return False


@contextmanager
def medir_etapa(recolector: RecolectorMetricas, etapa: str) -> Any:
    """
    Mide la duración de un bloque de código y la anota como métrica de la etapa indicada.
    Recibe el recolector donde se registra la duración y el nombre con el que se identifica la etapa.
    No entrega ningún valor al bloque, puesto que su única función consiste en delimitar el tramo que se mide.
    Un uso típico es el que sigue::

        with medir_etapa(recolector, "ingesta"):
            datos = leer_archivo(ruta)
    """
    inicio = time.perf_counter()
    try:
        yield
    finally:
        transcurrido = time.perf_counter() - inicio
        recolector.registrar_duracion(etapa, transcurrido)
        registrador.info(
            "Etapa finalizada",
            extra={"etapa": etapa, "duracion_segundos": round(transcurrido, 3)},
        )
