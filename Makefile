# Atajos para las operaciones habituales del proyecto.
#
# El archivo existe para que nadie tenga que recordar la sintaxis larga de docker compose ni el orden de los pasos.
# Al respecto, cada objetivo hace una sola cosa y su nombre dice cuál.
#
# En Windows, make se instala con "winget install GnuWin32.Make".
# En caso de preferir no instalarlo, los comandos se copian directamente desde este archivo, puesto que están escritos tal como se ejecutan.

.DEFAULT_GOAL := ayuda
.PHONY: ayuda instalar pruebas cobertura lint formato pipeline datos \
        levantar apagar reiniciar construir registros estado limpiar \
        dbt-construir dbt-probar dbt-documentar spark observabilidad \
        airflow-disparar verificar todo

PYTHON := python
COMPOSE := docker compose

# -----------------------------------------------------------------------------
# Ayuda
# -----------------------------------------------------------------------------

ayuda:
	@echo ""
	@echo "  Pipeline de ventas minoristas"
	@echo "  ============================="
	@echo ""
	@echo "  Entorno local"
	@echo "    make instalar          Crea el entorno virtual e instala dependencias"
	@echo "    make datos             Descarga el conjunto de datos completo"
	@echo "    make pipeline          Corre el pipeline en la máquina local"
	@echo ""
	@echo "  Calidad del código"
	@echo "    make pruebas           Ejecuta la batería de pruebas"
	@echo "    make cobertura         Ejecuta las pruebas midiendo cobertura"
	@echo "    make lint              Revisa el estilo del código"
	@echo "    make formato           Corrige automáticamente lo que se pueda"
	@echo "    make verificar         Lint más pruebas, igual que en integración continua"
	@echo ""
	@echo "  Infraestructura"
	@echo "    make construir         Construye las imágenes de Docker"
	@echo "    make levantar          Levanta todos los servicios"
	@echo "    make observabilidad    Levanta solo Prometheus y Grafana"
	@echo "    make apagar            Detiene los servicios"
	@echo "    make estado            Muestra el estado de los contenedores"
	@echo "    make registros         Sigue los registros de todos los servicios"
	@echo "    make limpiar           Borra contenedores, volúmenes y resultados"
	@echo ""
	@echo "  Etapas dentro de Docker"
	@echo "    make dbt-construir     Construye los modelos del almacén"
	@echo "    make dbt-probar        Corre las pruebas de datos de dbt"
	@echo "    make spark             Lanza el análisis distribuido"
	@echo "    make airflow-disparar  Dispara el grafo principal"
	@echo ""
	@echo "    make todo              Levanta la pila y ejecuta el flujo completo"
	@echo ""

# -----------------------------------------------------------------------------
# Entorno local
# -----------------------------------------------------------------------------

instalar:
	$(PYTHON) -m venv .venv
	.venv/bin/pip install --upgrade pip || .venv/Scripts/pip.exe install --upgrade pip
	.venv/bin/pip install -r requisitos-desarrollo.txt || .venv/Scripts/pip.exe install -r requisitos-desarrollo.txt
	@echo "Entorno listo. Activarlo con 'source .venv/bin/activate' o '.venv\\Scripts\\activate'"

datos:
	$(PYTHON) scripts/descargar_dataset.py

pipeline:
	$(PYTHON) ejecutar_pipeline.py --sin-almacen --sin-metricas --formato-log texto

# -----------------------------------------------------------------------------
# Calidad del código
# -----------------------------------------------------------------------------

pruebas:
	$(PYTHON) -m pytest pruebas -v

cobertura:
	$(PYTHON) -m pytest pruebas --cov=trabajos --cov-report=term-missing --cov-report=html

lint:
	$(PYTHON) -m ruff check trabajos pruebas orquestacion ejecutar_pipeline.py scripts

formato:
	$(PYTHON) -m ruff check --fix trabajos pruebas orquestacion ejecutar_pipeline.py scripts
	$(PYTHON) -m ruff format trabajos pruebas orquestacion ejecutar_pipeline.py scripts

verificar: lint pruebas
	@echo "Todas las verificaciones pasaron."

# -----------------------------------------------------------------------------
# Infraestructura
# -----------------------------------------------------------------------------

construir:
	$(COMPOSE) build

levantar:
	$(COMPOSE) --profile completo up -d
	@echo ""
	@echo "  Airflow        http://localhost:8080   usuario admin, clave admin"
	@echo "  Grafana        http://localhost:3000   usuario admin, clave admin"
	@echo "  Prometheus     http://localhost:9090"
	@echo "  Spark          http://localhost:8081"
	@echo "  Pushgateway    http://localhost:9091"
	@echo ""

observabilidad:
	$(COMPOSE) --profile observabilidad up -d

apagar:
	$(COMPOSE) --profile completo --profile herramientas down

reiniciar: apagar levantar

estado:
	$(COMPOSE) ps

registros:
	$(COMPOSE) logs -f --tail=100

limpiar:
	$(COMPOSE) --profile completo --profile herramientas down -v
	rm -rf salida/* dbt/target dbt/dbt_packages dbt/logs orquestacion/logs .pytest_cache .ruff_cache htmlcov
	@echo "Entorno limpio."

# -----------------------------------------------------------------------------
# Etapas dentro de Docker
# -----------------------------------------------------------------------------

ejecutar-docker:
	$(COMPOSE) --profile herramientas run --rm pipeline

dbt-construir:
	$(COMPOSE) --profile herramientas run --rm dbt deps
	$(COMPOSE) --profile herramientas run --rm dbt run

dbt-probar:
	$(COMPOSE) --profile herramientas run --rm dbt test

dbt-documentar:
	$(COMPOSE) --profile herramientas run --rm dbt docs generate

spark:
	$(COMPOSE) --profile spark up -d spark-maestro spark-trabajador
	$(COMPOSE) exec spark-maestro spark-submit \
		--master spark://spark-maestro:7077 \
		trabajos/spark/agregado_ventas.py

airflow-disparar:
	$(COMPOSE) exec airflow-programador airflow dags unpause ventas_minoristas_diario
	$(COMPOSE) exec airflow-programador airflow dags trigger ventas_minoristas_diario

todo: construir levantar
	@echo "Esperando a que los servicios terminen de arrancar..."
	@sleep 60
	$(MAKE) ejecutar-docker
	$(MAKE) dbt-construir
	$(MAKE) dbt-probar
	@echo "Flujo completo ejecutado."
