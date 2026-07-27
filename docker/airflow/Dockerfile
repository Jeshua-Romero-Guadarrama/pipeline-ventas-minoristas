# Imagen de Airflow ampliada con todo lo que necesita el pipeline.
#
# Sobre la imagen oficial se agregan tres cosas.
# En primer lugar, el entorno de ejecución de Java, puesto que el controlador de Spark corre dentro de este contenedor.
# A continuación, las dependencias del pipeline, que son las mismas que se usan en local.
# Por último, dbt, instalado en un entorno virtual separado.
#
# La última decisión merece una explicación.
# Dado que Airflow y dbt fijan versiones distintas de varias librerías compartidas, meterlos en el mismo entorno termina en un conflicto imposible de resolver.
# En cambio, aislar dbt en su propio entorno virtual y llamarlo por su ruta absoluta evita el problema por completo.

FROM apache/airflow:2.10.5-python3.12

# La instalación de paquetes del sistema exige privilegios de root.
USER root

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        openjdk-17-jre-headless \
        procps \
        curl \
        ca-certificates \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# El paso siguiente instala los certificados de confianza adicionales.
# Cabe señalar que algunas redes reemplazan el certificado de los sitios que se visitan por uno propio de la organización.
# Puesto que el anfitrión confía en ese certificado porque lo tiene instalado y el contenedor no, toda descarga falla.
# En caso de que la carpeta esté vacía el paso no hace nada, de modo que la construcción funciona igual en una red sin interceptación.
COPY docker/certificados/ /usr/local/share/ca-certificates/extra/
RUN update-ca-certificates || true

# PySpark ubica la máquina virtual de Java a través de la variable siguiente.
ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
ENV PATH="${JAVA_HOME}/bin:${PATH}"
ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
ENV PIP_CERT=/etc/ssl/certs/ca-certificates.crt

# A continuación, se preparan de antemano la carpeta donde se monta el proyecto y la que alojará el entorno de dbt.
RUN mkdir -p /opt/proyecto /opt/dbt_entorno \
    && chown -R airflow:root /opt/proyecto /opt/dbt_entorno

USER airflow

# Las dependencias del pipeline se instalan aplicando las restricciones oficiales de Airflow, para que la resolución no rompa las versiones que la imagen ya trae.
# Por ello requisitos.txt fija exactamente las mismas versiones que ese archivo de restricciones.
ARG RESTRICCIONES_AIRFLOW=https://raw.githubusercontent.com/apache/airflow/constraints-2.10.5/constraints-3.12.txt

COPY requisitos.txt /tmp/requisitos.txt
RUN pip install --no-cache-dir --constraint "${RESTRICCIONES_AIRFLOW}" -r /tmp/requisitos.txt

# Los complementos de Airflow van sin versión fija a propósito.
# Puesto que el archivo de restricciones ya define cuál corresponde a esta versión de Airflow, fijarla también acá solo genera conflictos cuando las dos no coinciden.
RUN pip install --no-cache-dir --constraint "${RESTRICCIONES_AIRFLOW}" \
        apache-airflow-providers-apache-spark \
        apache-airflow-providers-postgres

# dbt se instala en su propio entorno virtual, aislado de las dependencias de Airflow.
RUN python -m venv /opt/dbt_entorno \
    && /opt/dbt_entorno/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/dbt_entorno/bin/pip install --no-cache-dir \
        dbt-core==1.9.1 \
        dbt-postgres==1.9.0

ENV PYTHONPATH=/opt/proyecto
ENV PATH="/opt/dbt_entorno/bin:${PATH}"

# La ubicación de Spark se declara de forma explícita en lugar de dejar que spark-submit la descubra.
# Al respecto, el guion que trae PySpark localiza su propia instalación importando el paquete, y esa importación falla cuando el proceso arranca desde un intérprete que no ve el directorio de paquetes del usuario.
# Tal situación es justamente la de las tareas que Airflow lanza con BashOperator, puesto que no cargan el perfil de la sesión.
# El síntoma es un error de atributo sobre un objeto nulo seguido de un código de salida 127, que no menciona la causa por ninguna parte.
ENV SPARK_HOME=/home/airflow/.local/lib/python3.12/site-packages/pyspark
ENV PYSPARK_PYTHON=/usr/local/bin/python
ENV PYSPARK_DRIVER_PYTHON=/usr/local/bin/python

WORKDIR /opt/proyecto
