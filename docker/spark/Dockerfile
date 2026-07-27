# Imagen del clúster de Spark, usada por el nodo maestro y por los trabajadores.
#
# La imagen se construye desde python:3.12-slim en lugar de tomar una de Spark ya armada, y el motivo es concreto.
# Dado que el controlador de Spark corre dentro del contenedor de Airflow, que usa Python 3.12, si los ejecutores usaran otra versión el trabajo fallaría al deserializar las funciones enviadas.
# En consecuencia, fijar la misma versión de Python y la misma de PySpark en ambos lados elimina esa clase de error.

FROM python:3.12-slim-bookworm

# Java es el entorno de ejecución real de Spark, mientras que Python únicamente lo maneja desde afuera.
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        openjdk-17-jre-headless \
        procps \
        curl \
        ca-certificates \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
ENV PATH="${JAVA_HOME}/bin:${PATH}"

# El paso siguiente instala los certificados de confianza adicionales.
# Cabe señalar que algunas redes reemplazan el certificado de los sitios que se visitan por uno propio de la organización.
# Puesto que el anfitrión confía en ese certificado porque lo tiene instalado y el contenedor no, toda descarga falla.
# En caso de que la carpeta esté vacía el paso no hace nada, de modo que la construcción funciona igual en una red sin interceptación.
COPY docker/certificados/ /usr/local/share/ca-certificates/extra/
RUN update-ca-certificates || true

ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
ENV PIP_CERT=/etc/ssl/certs/ca-certificates.crt

# La versión de PySpark tiene que coincidir con la de la imagen de Airflow, donde corre el controlador.
# De ahí que un desajuste entre el controlador y los ejecutores produzca un error al deserializar que no dice nada sobre su causa real.
RUN pip install --no-cache-dir \
        pyspark==3.5.4 \
        pandas==2.1.4 \
        pyarrow==19.0.0 \
        numpy==1.26.4 \
        SQLAlchemy==1.4.54 \
        psycopg2-binary==2.9.10 \
        prometheus_client==0.21.1 \
        python-dotenv==1.0.1 \
        PyYAML==6.0.2 \
        duckdb==1.1.3

# SPARK_HOME apunta al lugar donde el paquete de PySpark deja los binarios del clúster.
ENV SPARK_HOME=/usr/local/lib/python3.12/site-packages/pyspark
ENV PATH="${SPARK_HOME}/bin:${SPARK_HOME}/sbin:${PATH}"
ENV PYTHONPATH=/opt/proyecto
ENV PYSPARK_PYTHON=/usr/local/bin/python
ENV PYSPARK_DRIVER_PYTHON=/usr/local/bin/python

# El trabajador guarda por defecto sus archivos de trabajo y sus registros dentro del propio SPARK_HOME, que aquí vive en el directorio de paquetes de Python y pertenece a root.
# Al correr el contenedor con el usuario cincuenta mil, esa carpeta no se puede crear y el trabajador entra en un ciclo de reinicios cuyo mensaje solo menciona un fallo al crear un directorio.
# Por ello se apuntan ambas rutas a carpetas creadas expresamente para el usuario que ejecuta el proceso.
ENV SPARK_WORKER_DIR=/opt/spark/trabajo
ENV SPARK_LOG_DIR=/opt/spark/registros
ENV SPARK_LOCAL_DIRS=/tmp/spark

# El clúster corre con el mismo identificador de usuario que Airflow, el cincuenta mil.
# Al respecto, la razón es concreta y cuesta bastante diagnosticarla la primera vez que aparece.
# Spark escribe primero en una carpeta temporal desde el ejecutor y después el controlador mueve esos archivos a su ubicación definitiva.
# En caso de que cada uno corriera con un usuario distinto, el traspaso fallaría con un error de renombrado que no menciona los permisos por ninguna parte.
RUN groupadd --gid 0 --non-unique raiz 2>/dev/null || true \
    && useradd --uid 50000 --gid 0 --create-home --shell /bin/bash airflow \
    && mkdir -p /opt/proyecto /opt/spark/registros /opt/spark/trabajo /tmp/spark \
    && chown -R 50000:0 /opt/proyecto /opt/spark /tmp/spark \
    && chmod -R g+rwX /opt/spark /tmp/spark

WORKDIR /opt/proyecto

COPY docker/spark/punto_de_entrada.sh /usr/local/bin/punto_de_entrada.sh
RUN chmod +x /usr/local/bin/punto_de_entrada.sh

ENTRYPOINT ["/usr/local/bin/punto_de_entrada.sh"]
CMD ["maestro"]
