#!/usr/bin/env bash
#
# Punto de entrada del contenedor de Spark.
#
# El mismo contenedor sirve para los tres roles del clúster según el argumento que reciba.
# De ese modo se evita mantener tres imágenes casi idénticas y se garantiza que el maestro, el trabajador y el cliente compartan exactamente las mismas versiones.
#
# Uso
#   punto_de_entrada.sh maestro       Levanta el nodo maestro.
#   punto_de_entrada.sh trabajador    Levanta un nodo trabajador.
#   punto_de_entrada.sh cliente       Deja el contenedor vivo para enviar trabajos.
#   punto_de_entrada.sh <comando>     Ejecuta cualquier otro comando.

set -euo pipefail

ROL="${1:-maestro}"
shift || true

MAESTRO_HOST="${SPARK_MAESTRO_HOST:-spark-maestro}"
MAESTRO_PUERTO="${SPARK_MAESTRO_PUERTO:-7077}"
INTERFAZ_PUERTO="${SPARK_INTERFAZ_PUERTO:-8080}"

case "${ROL}" in
  maestro)
    echo "Iniciando el nodo maestro de Spark en ${MAESTRO_HOST}:${MAESTRO_PUERTO}"
    exec "${SPARK_HOME}/bin/spark-class" org.apache.spark.deploy.master.Master \
      --host "${MAESTRO_HOST}" \
      --port "${MAESTRO_PUERTO}" \
      --webui-port "${INTERFAZ_PUERTO}"
    ;;

  trabajador)
    echo "Iniciando un nodo trabajador conectado a spark://${MAESTRO_HOST}:${MAESTRO_PUERTO}"
    exec "${SPARK_HOME}/bin/spark-class" org.apache.spark.deploy.worker.Worker \
      "spark://${MAESTRO_HOST}:${MAESTRO_PUERTO}" \
      --webui-port "${INTERFAZ_PUERTO}"
    ;;

  cliente)
    echo "Contenedor cliente listo para enviar trabajos al clúster"
    exec tail -f /dev/null
    ;;

  *)
    exec "${ROL}" "$@"
    ;;
esac
