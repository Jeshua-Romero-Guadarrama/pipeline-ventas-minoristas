"""
Configuración unificada de los logs para todo el pipeline.
Los logs salen en formato JSON por una razón concreta, puesto que cuando el pipeline corre dentro de Docker la salida estándar termina en el recolector de logs y un formato estructurado permite filtrar por etapa, por nivel o por cantidad de filas sin escribir expresiones regulares frágiles.
Para el desarrollo local existe además el formato de texto plano, más cómodo de leer en la terminal, y la elección entre uno y otro se hace con la variable de entorno FORMATO_LOG.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime
from typing import Any

# Los campos que siguen los agrega el módulo logging por su cuenta y no aportan valor en la salida JSON, motivo por el cual se descartan al serializar.
_CAMPOS_INTERNOS = frozenset(
    {
        "args",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)


class FormateadorJson(logging.Formatter):
    """
    Convierte cada registro de log en una línea JSON.
    Cabe señalar que cualquier dato adicional que se pase con el argumento extra se incorpora al objeto JSON como un campo más, de manera que se puede dejar constancia del conteo de filas o del nombre de la etapa sin ensuciar el mensaje de texto.
    """

    def format(self, registro: logging.LogRecord) -> str:
        """
        Serializa a JSON el registro de log que recibe.
        Dicho registro es el objeto que arma el módulo logging con toda la información del evento.
        Devuelve una cadena JSON de una sola línea.
        """
        cuerpo: dict[str, Any] = {
            "momento": datetime.fromtimestamp(registro.created, tz=UTC).isoformat(),
            "nivel": registro.levelname,
            "origen": registro.name,
            "mensaje": registro.getMessage(),
        }

        for clave, valor in registro.__dict__.items():
            if clave not in _CAMPOS_INTERNOS and not clave.startswith("_"):
                cuerpo[clave] = valor

        if registro.exc_info:
            cuerpo["excepcion"] = self.formatException(registro.exc_info)

        return json.dumps(cuerpo, ensure_ascii=False, default=str)


def configurar_registro(
    nivel: str | None = None, formato: str | None = None, forzar: bool = False
) -> None:
    """
    Deja el sistema de registro listo para el resto de la ejecución.
    Recibe el nivel mínimo que se va a emitir, valor que se lee de NIVEL_LOG cuando se omite, y el formato deseado, que vale "json" o "texto" y se lee de FORMATO_LOG cuando tampoco se indica.
    El tercer parámetro, forzar, reemplaza los manejadores existentes aunque ya haya alguno (solo tiene sentido pedirlo desde el punto de entrada de línea de comandos).
    Cuando el pipeline se ejecuta por su cuenta, esta función configura el logger raíz para que todo salga por la salida estándar con el formato elegido.
    En cambio, cuando corre dentro de otra aplicación que ya configuró el registro, y el caso concreto es una tarea de Airflow, la función no toca nada y se limita a ajustar los niveles para que los mensajes lleguen a los manejadores que ya existen.
    La distinción anterior no es un detalle de estilo, puesto que resuelve una falla concreta y difícil de diagnosticar.
    Al respecto, Airflow ejecuta cada tarea redirigiendo la salida estándar hacia su propio sistema de registro, con el fin de guardar en el archivo de la tarea todo lo que el código imprima.
    En razón de ello, si en ese contexto se reemplazan los manejadores del logger raíz por uno que escribe a la salida estándar, se arma un lazo en el que cada mensaje va a la salida estándar, desde ahí vuelve a entrar al sistema de registro, se emite otra vez y así sucesivamente.
    En consecuencia, el consumo de memoria crece de golpe y el sistema operativo termina matando el proceso sin dejar ningún error que explique nada.
    En definitiva, la regla general que se aplica acá vale para cualquier código que pueda importarse desde otro programa, ya que un módulo no debería apropiarse del logger raíz porque no es suyo.
    """
    nivel_elegido = (nivel or os.environ.get("NIVEL_LOG", "INFO")).upper()
    formato_elegido = (formato or os.environ.get("FORMATO_LOG", "json")).lower()

    raiz = logging.getLogger()

    # En caso de que ya existan manejadores, el registro lo configuró alguien más y esa configuración ajena se respeta.
    if raiz.handlers and not forzar:
        raiz.setLevel(min(raiz.level or logging.INFO, getattr(logging, nivel_elegido, logging.INFO)))
    else:
        manejador = logging.StreamHandler(sys.stdout)
        if formato_elegido == "json":
            manejador.setFormatter(FormateadorJson())
        else:
            manejador.setFormatter(
                logging.Formatter(
                    fmt="%(asctime)s [%(levelname)-8s] %(name)s | %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S",
                )
            )

        raiz.handlers.clear()
        raiz.addHandler(manejador)
        raiz.setLevel(nivel_elegido)

    # Las librerías de terceros resultan muy conversadoras en el nivel INFO y terminan tapando los mensajes propios del pipeline, motivo por el cual se les sube el umbral.
    for ruidosa in ("py4j", "pyspark", "urllib3", "botocore", "sqlalchemy.engine"):
        logging.getLogger(ruidosa).setLevel(logging.WARNING)


def obtener_registrador(nombre: str) -> logging.Logger:
    """
    Devuelve una instancia de Logger lista para usar, identificada con el nombre que se le indique.
    Dicho nombre suele ser __name__, es decir, el del módulo que hace la llamada.
    """
    return logging.getLogger(nombre)
