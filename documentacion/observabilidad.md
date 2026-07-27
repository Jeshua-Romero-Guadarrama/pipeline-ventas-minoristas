# Observabilidad

Un pipeline sin observabilidad es un pipeline en el que uno confía por costumbre.
El presente documento describe qué se mide, cómo se recolecta y qué se hace con esa información.

El principio que guía todo el diseño es que la observabilidad tiene que responder tres preguntas en un orden determinado.
En primer lugar, si está funcionando.
A continuación, si está produciendo lo que debería.
Por último, en caso de que algo ande mal, dónde está el problema.

---

## Arquitectura de recolección

```
                      ┌──────────────────────┐
   pipeline ──push──> │    Pushgateway       │ ──┐
   (por lotes)        │    puerto 9091       │   │
                      └──────────────────────┘   │
                                                 │
                      ┌──────────────────────┐   │   ┌────────────┐
   Airflow  ──statsd─>│  statsd-exportador   │ ──┼──>│ Prometheus │
   (UDP 9125)         │    puerto 9102       │   │   │ puerto 9090│
                      └──────────────────────┘   │   └─────┬──────┘
                                                 │         │
                      ┌──────────────────────┐   │         │
   PostgreSQL ───────>│ postgres-exportador  │ ──┘         │
                      │    puerto 9187       │             v
                      └──────────────────────┘      ┌────────────┐
                                                    │  Grafana   │
                                                    │ puerto 3000│
                                                    └────────────┘
```

Cada fuente responde una pregunta distinta.

| Fuente | Pregunta que responde |
| --- | --- |
| Pushgateway | Qué produjo la última corrida del pipeline |
| statsd-exportador | Cómo se está comportando el orquestador |
| postgres-exportador | Cómo está el almacén analítico |
| Prometheus sobre sí mismo | Si el propio monitoreo está sano |

### Por qué Pushgateway y no un endpoint

El pipeline es un proceso por lotes que arranca, procesa y termina.
Siempre que expusiera un endpoint de métricas, para cuando Prometheus fuera a consultarlo el proceso ya no existiría.

El Pushgateway es un intermediario que guarda las métricas que le empujan y las mantiene disponibles para que Prometheus las lea.
Dicho de otro modo, se trata de la solución estándar para trabajos de duración corta.

Su limitación conocida es que no distingue entre un trabajo que dejó de correr y uno que corrió pero no cambió sus valores.
Por ello, el pipeline publica también la marca de tiempo de la última corrida exitosa, y sobre esa marca se define la alerta de datos desactualizados.

### Por qué StatsD para Airflow

Airflow emite sus métricas internas por el protocolo StatsD, que es lo que soporta de forma nativa.
El exportador las traduce al modelo de datos de Prometheus.

Conviene precisar que la traducción no es trivial.
Airflow emite nombres como `airflow.dagrun.duration.success.ventas_minoristas_diario`, donde el nombre del grafo está dentro de la cadena, mientras que Prometheus espera un nombre estable y etiquetas que varíen.
El archivo `observabilidad/statsd/mapeo_airflow.yml` define esa correspondencia.
Sin él, cada grafo generaría una métrica distinta y sería imposible graficarlos juntos.

---

## Métricas del pipeline

### De ejecución

| Métrica | Tipo | Etiquetas | Para qué sirve |
| --- | --- | --- | --- |
| `pipeline_ventas_ejecucion_exitosa` | medidor | ninguna | Vale 1 si la última corrida terminó bien |
| `pipeline_ventas_ultima_ejecucion_exitosa_timestamp` | medidor | ninguna | Base de la alerta de datos viejos |
| `pipeline_ventas_duracion_segundos` | medidor | `etapa` | Detectar qué etapa se está degradando |
| `pipeline_ventas_filas_procesadas` | medidor | `etapa` | Ver dónde se pierden registros |

La métrica de filas por etapa merece una nota.
Comparar el valor entre etapas muestra de un vistazo dónde se van los registros, que suele ser la primera pregunta cuando un número del tablero no cierra.
Por ejemplo, si `ingesta` marca un millón y `validacion` marca ochocientos mil, el problema está en las reglas de calidad y no en la transformación.

### De calidad

| Métrica | Tipo | Etiquetas | Para qué sirve |
| --- | --- | --- | --- |
| `pipeline_ventas_filas_rechazadas_total` | contador | `regla` | Saber qué regla descarta más |
| `pipeline_ventas_porcentaje_rechazo` | medidor | ninguna | Vigilar la salud general del origen |

### De negocio

| Métrica | Tipo | Para qué sirve |
| --- | --- | --- |
| `pipeline_ventas_ingreso_total` | medidor | Detectar saltos que indican duplicación |
| `pipeline_ventas_productos_distintos` | medidor | Detectar catálogos incompletos |
| `pipeline_ventas_dias_cubiertos` | medidor | Detectar períodos faltantes |

Publicar métricas de negocio junto a las técnicas no es habitual, pero resulta muy útil.
La razón es que un pipeline puede terminar sin errores y aun así haber producido algo incorrecto.
Siempre que el ingreso total se duplique de un día para otro sin que haya cambiado el volumen, la explicación casi siempre es que se procesó el archivo dos veces, y esa métrica lo hace evidente de inmediato.

### Del almacén, publicadas por el grafo de vigilancia

| Métrica | Etiquetas | Para qué sirve |
| --- | --- | --- |
| `almacen_filas_por_tabla` | `tabla` | Vigilar el crecimiento de cada tabla |
| `almacen_dias_publicados` | ninguna | Cobertura temporal del almacén |
| `almacen_diferencia_entre_capas` | ninguna | Coherencia entre lo crudo y lo publicado |
| `almacen_vigilancia_completada` | ninguna | Si la propia vigilancia pudo correr |

---

## Alertas

Las alertas están definidas en `observabilidad/prometheus/reglas_alertas.yml`, y cada una tiene una acción concreta documentada en el runbook.
Al respecto, una alerta que nadie sabe cómo atender solo genera ruido y termina ignorándose, motivo por el cual no hay alertas informativas.

| Alerta | Severidad | Condición | Espera |
| --- | --- | --- | --- |
| `PipelineFallo` | crítica | Última corrida con error | 1 min |
| `ProgramadorSinLatido` | crítica | Airflow dejó de latir | 5 min |
| `ServicioCaido` | crítica | Un objetivo no responde | 2 min |
| `DatosDesactualizados` | alta | Más de 26 horas sin corrida buena | 10 min |
| `CaidaAbruptaDeVolumen` | alta | Menos de la mitad del promedio semanal | 15 min |
| `AlmacenSinConexionesDisponibles` | alta | Más del 80 por ciento de conexiones usadas | 5 min |
| `TareasDeAirflowFallando` | alta | Más de 3 fallos en una hora | 5 min |
| `CalidadDeDatosDegradada` | media | Rechazo por encima del 10 por ciento | 5 min |
| `PipelineDemasiadoLento` | media | Una etapa por encima de 15 minutos | 2 min |

### Sobre la cláusula de espera

Todas las alertas tienen un período durante el cual la condición debe mantenerse antes de disparar.
Dicho período existe para evitar avisos por un pico momentáneo, dado que una métrica que se recupera sola en dos minutos no necesitaba que nadie mirara.

Los tiempos no son arbitrarios.
Las alertas críticas esperan poco porque el costo de reaccionar tarde es alto.
Las de calidad, en cambio, esperan más porque un pico aislado de rechazos suele resolverse en la corrida siguiente.

### Sobre la elección de umbrales

El umbral de veintiséis horas para datos desactualizados sale de que el pipeline corre una vez por día.
Veinticuatro horas dispararía en cada corrida que arranque unos minutos tarde, de manera que veintiséis dan margen sin dejar pasar un problema real.

El umbral de diez por ciento para calidad está por debajo del quince que hace fallar el pipeline.
La separación entre ambos umbrales es deliberada, puesto que entre diez y quince el pipeline publica igual pero avisa, lo que da tiempo a investigar sin que el servicio de datos se interrumpa.

---

## Tablero de Grafana

El tablero se aprovisiona por archivo y no se importa a mano.
De ese modo la configuración queda versionada en el repositorio, se revisa junto con el código y se reconstruye igual en cualquier máquina.

Está organizado en cuatro filas que siguen el orden en el que uno investiga un problema.

### Estado general

Son cinco indicadores que responden la pregunta más básica, es decir, si el sistema está funcionando.

- Resultado de la última corrida, en verde o rojo
- Antigüedad de los datos, en amarillo pasadas 24 horas y en rojo pasadas 26
- Ingreso total procesado
- Productos distintos
- Días cubiertos

### Volumen y calidad

Son cuatro paneles que responden si lo que produjo es razonable.

- Filas al final de cada etapa, con una serie por etapa
- Porcentaje de rechazo con las líneas de umbral marcadas
- Filas rechazadas por regla, en barras horizontales
- Duración de cada etapa, apiladas para ver el tiempo total

### Orquestación

Son tres paneles sobre la salud de Airflow.

- Latido del programador
- Tareas finalizadas por estado, con las fallidas en rojo
- Ranuras libres y tareas en cola

### Almacén

Son tres paneles sobre la infraestructura de datos.

- Disponibilidad de PostgreSQL
- Conexiones abiertas por base
- Servicios que responden

### Consultas útiles

```promql
# Cuánto hace que no hay una corrida buena
time() - pipeline_ventas_ultima_ejecucion_exitosa_timestamp

# Qué proporción de filas sobrevive a la validación
pipeline_ventas_filas_procesadas{etapa="validacion"}
  / pipeline_ventas_filas_procesadas{etapa="ingesta"}

# Duración total de la corrida
sum(pipeline_ventas_duracion_segundos)

# Las tres reglas que más descartan
topk(3, pipeline_ventas_filas_rechazadas_total)

# Variación del ingreso respecto de hace un día
pipeline_ventas_ingreso_total
  - pipeline_ventas_ingreso_total offset 1d
```

---

## Logs

Los logs salen en JSON por defecto.
Dentro de Docker la salida estándar termina en el recolector de logs, y un formato estructurado permite filtrar por etapa, por nivel o por cantidad de filas sin escribir expresiones regulares frágiles.

```json
{
  "momento": "2026-07-26T14:13:04.512Z",
  "nivel": "INFO",
  "origen": "trabajos.validaciones",
  "mensaje": "Validación de calidad finalizada",
  "filas_entrada": 1067371,
  "filas_validas": 1007894,
  "filas_rechazadas": 59477,
  "porcentaje_rechazo": 5.5723
}
```

Cualquier dato que se pase con el argumento `extra` se incorpora como campo del objeto JSON.
De ese modo se registran conteos sin ensuciar el mensaje de texto.

Para desarrollo local existe el formato de texto plano, más cómodo de leer en la terminal.

```bash
python ejecutar_pipeline.py --formato-log texto
```

Las librerías de terceros tienen el umbral subido a advertencia, porque en nivel informativo son muy conversadoras y tapan los mensajes propios del pipeline.

### Consultas frecuentes sobre los logs

```bash
# Solo los errores del pipeline
docker compose logs airflow-programador | grep '"nivel":"ERROR"'

# Cuántas filas dejó cada etapa
docker compose logs pipeline | grep filas_registradas

# Duración de cada etapa
docker compose logs pipeline | grep duracion_segundos
```

---

## Qué no está cubierto

Vale la pena ser explícito sobre los límites del diseño actual.

| Aspecto | Estado | Por qué |
| --- | --- | --- |
| Trazas distribuidas | No hay | El pipeline es secuencial, una traza no agregaría información |
| Envío de alertas | Definidas pero sin destinatario | Falta configurar Alertmanager con un canal real |
| Retención larga | 15 días en Prometheus | Suficiente para operar, insuficiente para análisis anual |
| Linaje a nivel de columna | No hay | Requiere un catálogo de datos, fuera del alcance |
| Muestreo de consultas lentas | No configurado | Quedaría activado con `pg_stat_statements` |

El punto de las alertas es el más relevante.
Las reglas están definidas y Prometheus las evalúa, pero sin Alertmanager configurado nadie recibe el aviso.
Agregarlo son unas veinte líneas en el compose más la configuración del canal de destino, y quedó fuera porque un canal de notificación real no se puede incluir en un repositorio público.
