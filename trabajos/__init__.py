"""
El presente paquete reúne la lógica del pipeline de ventas.
Al respecto, cada módulo cubre una etapa concreta del flujo y se puede usar de forma independiente, lo que facilita probarlo y reutilizarlo desde Airflow, desde la línea de comandos o desde un cuaderno de análisis.

Los módulos disponibles son los que siguen.
El módulo configuracion reúne las rutas, los parámetros y la lectura de las variables de entorno.
El módulo registro unifica la configuración de los logs en formato JSON.
El módulo metricas publica las métricas hacia Prometheus.
El módulo ingesta lee el archivo crudo y normaliza los nombres de las columnas.
El módulo validaciones aplica las reglas de calidad y aparta las filas rechazadas.
El módulo transformaciones calcula el ingreso total y las agregaciones de negocio.
El módulo persistencia escribe los resultados en Parquet y en CSV.
El módulo carga_almacen deja esos mismos resultados cargados en PostgreSQL.
"""

__version__ = "1.0.0"
