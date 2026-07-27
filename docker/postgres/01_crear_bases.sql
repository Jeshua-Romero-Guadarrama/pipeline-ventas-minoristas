-- Inicialización del servidor PostgreSQL del proyecto.
--
-- Un solo servidor aloja dos bases con propósitos muy distintos.
-- En primer lugar, la base airflow guarda el estado del orquestador, es decir qué corrió, cuándo y con qué resultado.
-- Por su parte, la base analitica guarda los datos del negocio.
--
-- Separarlas importa por dos razones concretas.
-- En caso de que se mezclaran, una consulta pesada de un analista podría trabar el planificador de tareas, y una restauración de cualquiera de las dos arrastraría a la otra.
-- Ahora bien, en un entorno productivo serían además dos servidores distintos, aunque para un proyecto de este alcance dos bases ya dan el aislamiento lógico necesario.
--
-- El presente archivo lo ejecuta la imagen oficial de PostgreSQL la primera vez que arranca con un volumen de datos vacío.

-- La primera base es la de metadatos del orquestador.
CREATE USER airflow WITH PASSWORD 'airflow';
CREATE DATABASE airflow OWNER airflow;
GRANT ALL PRIVILEGES ON DATABASE airflow TO airflow;

-- La segunda base es la del almacén analítico.
CREATE USER analitica WITH PASSWORD 'analitica';
CREATE DATABASE analitica OWNER analitica;
GRANT ALL PRIVILEGES ON DATABASE analitica TO analitica;

-- Los esquemas se crean dentro de la base analitica y no en la base por defecto.
\connect analitica

-- El esquema crudo recibe lo que escribe el pipeline de Python sin ninguna modelización.
-- Al respecto, constituye la zona de aterrizaje y nadie debería consultarla directamente.
CREATE SCHEMA IF NOT EXISTS crudo AUTHORIZATION analitica;

-- El esquema preparado guarda los modelos intermedios que construye dbt.
CREATE SCHEMA IF NOT EXISTS preparado AUTHORIZATION analitica;

-- El esquema publicado guarda las tablas finales, que son las únicas que consumen los tableros y las consultas de negocio.
CREATE SCHEMA IF NOT EXISTS publicado AUTHORIZATION analitica;

GRANT ALL ON SCHEMA crudo, preparado, publicado TO analitica;

-- La vista siguiente sirve de apoyo al exportador de métricas.
-- De ese modo, Prometheus conoce el tamaño de las tablas del almacén sin necesidad de permisos amplios.
CREATE OR REPLACE VIEW publicado.vista_tamanio_tablas AS
SELECT
    schemaname AS esquema,
    relname AS tabla,
    n_live_tup AS filas_estimadas,
    pg_total_relation_size(relid) AS bytes_totales
FROM pg_stat_user_tables
WHERE schemaname IN ('crudo', 'preparado', 'publicado');

GRANT SELECT ON publicado.vista_tamanio_tablas TO analitica;
