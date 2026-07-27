# Calidad del código y buenas prácticas

El presente documento recoge las convenciones que sigue el proyecto y el motivo de cada una.
Cabe señalar que no son reglas por gusto, puesto que cada una resuelve un problema que aparece cuando el código lo lee otra persona o cuando hay que modificarlo seis meses después.

---

## Convenciones generales

### Todo en español

Los nombres de variables, funciones, módulos, carpetas, docstrings y comentarios se escriben en español.
La única excepción son las palabras reservadas del lenguaje y los nombres de librerías de terceros.

El motivo es la coherencia.
Al respecto, un código que mezcla `datos_validos` con `row_count` obliga a cambiar de idioma mentalmente en cada línea, y ese costo se paga en cada lectura.

### Docstrings en todas las funciones públicas

El estilo seguido es el de Google, con secciones de argumentos, valor de retorno y excepciones.

```python
def calcular_ingreso_total(datos: pd.DataFrame) -> pd.DataFrame:
    """Agrega la columna de ingreso total a nivel de línea de factura.

    El redondeo a dos decimales se aplica en este punto y no al final. La
    razón es que el importe de una línea de factura es un valor monetario
    real, y sumar valores ya redondeados da el mismo resultado que muestra el
    sistema contable de origen, que es contra lo que se va a comparar.

    Args:
        datos: Tabla con las columnas cantidad y precio_unitario.

    Returns:
        Una copia de la tabla con la columna ingreso_total agregada.

    Raises:
        KeyError: Si falta alguna de las dos columnas necesarias.
    """
```

Lo importante no es la sección de argumentos, que casi siempre resulta evidente.
Lo importante es el párrafo que explica **por qué** se hizo así, dado que un docstring que repite lo que dice la firma de la función no aporta nada.

### Anotaciones de tipo en todo el código

```python
def validar(datos: pd.DataFrame, configuracion: ConfiguracionPipeline) -> ResultadoValidacion:
```

Las anotaciones documentan sin comentarios, permiten que el editor autocomplete y detecte errores antes de ejecutar, y obligan a pensar qué recibe y qué devuelve cada función.

Adicionalmente, se usa `from __future__ import annotations` en todos los módulos, con el fin de poder escribir sintaxis moderna de tipos manteniendo la compatibilidad con Python 3.11.

### Comentarios que explican decisiones, no acciones

```python
# Mal, repite lo que ya dice el código
# Suma la columna de ingreso
total = datos["ingreso_total"].sum()

# Bien, explica algo que el código no puede decir
# El valor por defecto de particiones de barajado en Spark es doscientos, un
# número pensado para clústeres grandes. Con este volumen eso genera cientos
# de archivos diminutos y el costo de coordinarlos supera al del cálculo.
.config("spark.sql.shuffle.partitions", "8")
```

---

## Diseño de los módulos

### Una responsabilidad por módulo

| Módulo | Su única responsabilidad |
| --- | --- |
| `configuracion.py` | Resolver rutas, umbrales y conexiones |
| `registro.py` | Formatear y encaminar los logs |
| `metricas.py` | Acumular y publicar métricas |
| `ingesta.py` | Leer el archivo y normalizar su forma |
| `validaciones.py` | Decidir qué fila es válida |
| `transformaciones.py` | Calcular las medidas de negocio |
| `persistencia.py` | Escribir y leer resultados |
| `carga_almacen.py` | Hablar con PostgreSQL |

La prueba de que la separación funciona es simple.
Siempre que agregar una regla de calidad obligue a tocar `transformaciones.py`, la separación está mal.

### Funciones puras en la capa de transformación

Todas las funciones de `transformaciones.py` reciben una tabla y devuelven otra, sin tocar disco ni variables globales.

```python
def agregar_por_producto_y_fecha(datos: pd.DataFrame) -> pd.DataFrame:
    ...
    agregado = agrupado.agg(...).reset_index()
    return agregado
```

De ese modo se puede probar cada regla de negocio con tablas de tres filas armadas a mano, sin levantar ninguna infraestructura.
De ahí que la batería de setenta pruebas corra en unos pocos segundos.

Ello significa además que ninguna función modifica su entrada, ya que se trabaja siempre sobre una copia.

```python
resultado = datos.copy()
resultado["ingreso_total"] = (cantidad * precio).round(2)
return resultado
```

Hay una prueba dedicada a verificar exactamente esto.

```python
def test_calcular_ingreso_no_modifica_la_tabla_original(ventas_validas):
    """La función es pura, devuelve una copia y deja la entrada intacta."""
    columnas_antes = list(ventas_validas.columns)
    calcular_ingreso_total(ventas_validas)
    assert list(ventas_validas.columns) == columnas_antes
```

### Excepciones propias por dominio

```python
class ErrorDeIngesta(Exception):
    """Se lanza cuando el archivo de entrada no se puede procesar."""

class ErrorDeCalidad(Exception):
    """Se lanza cuando los datos no alcanzan el nivel mínimo aceptable."""

class ErrorDePersistencia(Exception):
    """Se lanza cuando no se puede escribir un resultado en disco."""
```

Las excepciones propias permiten que quien orquesta distinga un problema de datos de un error de programación, distinción que se traduce en códigos de salida diferentes.

```python
except (ErrorDeIngesta, ErrorDeCalidad):
    return 1        # problema de datos, no reintentar sin revisar
except Exception:
    return 2        # error inesperado, probablemente un fallo del código
```

### Configuración inmutable y construida bajo demanda

```python
@dataclass(frozen=True)
class ConfiguracionPipeline:
    ...

def obtener_configuracion() -> ConfiguracionPipeline:
    return ConfiguracionPipeline()
```

El atributo `frozen=True` evita que una parte del código modifique la configuración y otra lea un valor distinto.

La instancia global de módulo quedó descartada en favor de la construcción en cada llamada, porque así las pruebas pueden alterar variables de entorno con `monkeypatch` y obtener una configuración distinta sin reiniciar el intérprete.

### Reglas de calidad como datos, no como código

```python
@dataclass(frozen=True)
class ReglaCalidad:
    nombre: str
    descripcion: str
    detectar: Callable[[pd.DataFrame], pd.Series]
```

Agregar una regla se reduce a agregar un elemento a una lista, sin tocar el motor que las aplica.
El nombre se usa en las métricas y en la cuarentena, mientras que la descripción aparece en el log y en el reporte, de modo que quien lee el resultado entiende qué se comprobó sin abrir el código.

---

## Manejo de errores

### Fallar temprano cuando el problema es de estructura

```python
faltantes = [c for c in COLUMNAS_OBLIGATORIAS if c not in datos.columns]
if faltantes:
    raise ErrorDeIngesta(
        f"El archivo de entrada no tiene las columnas obligatorias {faltantes}. "
        f"Columnas encontradas: {sorted(datos.columns)}"
    )
```

El mensaje incluye qué falta y qué se encontró.
En cambio, un error que dice solo "falta una columna" obliga a abrir el archivo para averiguar cuál.

### Tolerar cuando el problema es de contenido

```python
convertidos["cantidad"] = pd.to_numeric(
    convertidos["cantidad"], errors="coerce"
).astype("Int64")
```

Un valor que no se puede convertir queda como nulo en lugar de cortar la lectura.
La fila afectada la detecta después la validación de nulos y termina en cuarentena con su motivo, resultado mucho más útil que una excepción sin contexto.

### Nunca dejar que la observabilidad rompa el pipeline

```python
try:
    push_to_gateway(...)
    return True
except Exception as error:  # noqa: BLE001
    # Se atrapa cualquier excepción a propósito. La observabilidad es un
    # apoyo y no puede hacer fallar una corrida que produjo datos.
    registrador.warning("No se pudieron publicar las métricas, la corrida continúa", ...)
    return False
```

El `noqa` está justificado con un comentario.
Conviene precisar que capturar `Exception` a secas suele ser mala señal, motivo por el cual cuando se hace hay que explicar por qué.

### Mensajes que dicen qué hacer

```python
raise ErrorDeIngesta(
    f"No se encontró el archivo de entrada en {ruta}. "
    "Generá la muestra con 'python scripts/generar_datos_ejemplo.py' "
    "o copiá el CSV original a datos/crudos/."
)
```

Un mensaje de error que además indica la solución ahorra una búsqueda en la documentación.

---

## Idempotencia

Toda operación de escritura borra su destino antes de escribir.

```python
def _limpiar_destino(ruta: Path) -> None:
    """Borra el destino anterior para que la escritura sea idempotente.

    Sin este paso, volver a correr el pipeline sobre una carpeta particionada
    dejaría conviviendo los archivos de la corrida vieja con los de la nueva y
    los conteos saldrían duplicados.
    """
    if ruta.is_dir():
        shutil.rmtree(ruta)
    elif ruta.exists():
        ruta.unlink()
```

De ese modo Airflow puede reintentar una tarea fallida sin consecuencias, motivo por el cual hay una prueba dedicada a comprobarlo.

```python
def test_correr_dos_veces_da_el_mismo_resultado(configuracion_temporal, archivo_de_entrada):
    """La reejecución es segura, que es lo que permite reintentar una tarea fallida."""
    primero = ejecutar(...)
    segundo = ejecutar(...)
    assert primero["metricas_negocio"] == segundo["metricas_negocio"]
```

---

## Estrategia de pruebas

### Datos de prueba pequeños y verificables a mano

```python
@pytest.fixture
def ventas_validas() -> pd.DataFrame:
    """Cinco líneas de factura que cumplen todas las reglas de calidad.

    Los importes están elegidos para que las sumas den números redondos y se
    puedan comprobar sin calculadora.
    """
```

Los valores esperados se documentan en el propio caso.

```python
def test_el_agregado_suma_las_lineas_de_la_misma_clave(ventas_validas):
    """Dos líneas del mismo producto y día se combinan en una sola fila.

    El producto 22086 vendió 25.00 y 50.00 el primero de diciembre,
    así que su fila del agregado tiene que valer 75.00.
    """
    ...
    assert fila["ingreso_total"].iloc[0] == 75.0
```

De ese modo, cuando una prueba falla, quien la lee puede verificar la cuenta sin ejecutar nada.

### Nombres que describen el comportamiento esperado

```python
def test_la_agregacion_conserva_el_ingreso_total(...)
def test_falla_cuando_se_supera_el_umbral_de_rechazo(...)
def test_un_destino_inalcanzable_no_rompe_la_corrida(...)
```

Así, la salida de pytest se lee como una especificación del sistema.

### Ninguna prueba necesita servicios externos

Cada caso arma sus propios datos y escribe en la carpeta temporal que pytest crea para él.
En consecuencia, la batería corre igual en una máquina sin Docker, sin red y sin el archivo de datos.

### Invariantes por encima de casos concretos

La prueba más valiosa del proyecto no comprueba un número, sino que comprueba una propiedad que tiene que cumplirse siempre.

```python
def test_la_agregacion_conserva_el_ingreso_total(ventas_validas):
    """Agregar no puede crear ni perder dinero.

    Se trata de la invariante más importante del pipeline. La suma del detalle y
    la suma del agregado tienen que coincidir hasta el último centavo.
    """
    assert round(detalle["ingreso_total"].sum(), 2) == round(agregado["ingreso_total"].sum(), 2)
```

La misma invariante se comprueba de nuevo en dbt, sobre el almacén ya construido, y una tercera vez en el grafo de vigilancia.

---

## Convenciones de SQL

### Consultas por etapas con expresiones de tabla comunes

```sql
with origen as (
    select * from {{ source('crudo', 'detalle_ventas') }}
),

normalizado as (
    select ... from origen
),

marcado as (
    select ... from normalizado
)

select * from marcado
```

Cada bloque hace una cosa y tiene nombre.
En cambio, una consulta de cien líneas con subconsultas anidadas hace lo mismo pero nadie puede leerla.

### Referencias en lugar de nombres de tabla

```sql
-- Mal
select * from analitica.crudo.detalle_ventas

-- Bien
select * from {{ source('crudo', 'detalle_ventas') }}
select * from {{ ref('prep_ventas') }}
```

De ese modo dbt puede construir el grafo de dependencias y ordenar la ejecución solo.
Siempre que mañana cambie el nombre de una tabla, se corrige en un único lugar.

### Macros para lo que se repite

```sql
{% macro a_importe(columna) -%}
    round(cast({{ columna }} as numeric), 2)
{%- endmacro %}
```

Sin la macro, en algún modelo se escribiría una escala distinta y los totales dejarían de cerrar entre capas por una diferencia de redondeo.

### Divisiones protegidas

```sql
{% macro division_segura(numerador, denominador) -%}
    case
        when coalesce({{ denominador }}, 0) = 0 then null
        else cast({{ numerador }} as numeric) / cast({{ denominador }} as numeric)
    end
{%- endmacro %}
```

En SQL una división por cero corta toda la consulta.
Devolver nulo resulta mucho más útil, porque el resto del modelo se construye igual y el vacío queda visible en el tablero.

---

## Herramientas de verificación

| Herramienta | Qué controla | Cuándo corre |
| --- | --- | --- |
| ruff check | Errores de estilo y fallas lógicas | Al guardar y en cada envío |
| ruff format | Formato uniforme | Al guardar |
| pytest | Comportamiento del código | Antes de cada envío |
| pytest-cov | Cobertura de las pruebas | En integración continua |
| dbt test | Corrección de los datos | Después de cada construcción |
| docker compose config | Sintaxis de la infraestructura | En integración continua |

Los conjuntos de reglas de ruff que se activan son los que atrapan errores reales, no preferencias.

```toml
select = ["E", "W", "F", "I", "B", "UP", "C4", "SIM"]
```

| Conjunto | Qué atrapa |
| --- | --- |
| `E`, `W` | Errores y advertencias de estilo |
| `F` | Variables sin usar, importaciones muertas, nombres indefinidos |
| `I` | Importaciones desordenadas |
| `B` | Fallas lógicas frecuentes, como valores mutables por defecto |
| `UP` | Sintaxis obsoleta que ya tiene reemplazo |
| `C4` | Comprensiones que se pueden simplificar |
| `SIM` | Construcciones innecesariamente complicadas |

Por su parte, se ignora `E501`, el largo máximo de línea, porque el formateador ya lo maneja y mantenerlo activo genera avisos sobre líneas que el propio formateador escribió.

---

## Qué se hizo a propósito y podría discutirse

Vale la pena ser explícito sobre las decisiones que no son obvias.

**Un motivo único por fila rechazada en lugar de la lista completa.** La lista de todas las reglas incumplidas quedó descartada, de manera que se pierde información sobre las filas que fallan varias.
A cambio, la suma de los conteos por regla coincide con el total de rechazos, y eso hace que el tablero sea interpretable sin explicación.

**Reemplazo completo de tabla en lugar de carga incremental.** La carga incremental se descartó porque, con este volumen, el reemplazo completo es la opción con menos formas de dejar datos a medias.
Lo que se pierde es la escalabilidad, dado que este esquema no acompaña un crecimiento fuerte del histórico.

**`Exception` capturado en la capa de métricas.** Normalmente se considera mala práctica y por eso se evita en el resto del código.
Aquí está justificado porque el objetivo explícito es que nada de esa capa pueda propagarse.

**Configuración construida en cada llamada.** La instancia global de módulo, que habría resultado levemente más barata, quedó descartada.
A cambio, las pruebas pueden alterar el entorno sin efectos entre casos.

**pandas en lugar de Polars o DuckDB.** Los dos son más rápidos en este tipo de carga, motivo por el cual la comparación no se decidió por rendimiento.
La elección de pandas responde a que el proyecto también es material de estudio y a que es lo que más gente sabe leer sin explicación previa.
