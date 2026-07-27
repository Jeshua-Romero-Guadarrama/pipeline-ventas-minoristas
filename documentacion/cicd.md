# Integración y entrega continua

El pipeline de CI/CD está definido en `.github/workflows/integracion-continua.yml` y se ejecuta con GitHub Actions.

El criterio de diseño consiste en dar la respuesta más útil en el menor tiempo.
Al respecto, las etapas rápidas y baratas corren primero, y las que necesitan levantar servicios solo se ejecutan si las anteriores pasaron.
De ese modo, un error de sintaxis se reporta en menos de un minuto en lugar de después de diez.

---

## Cuándo se dispara

| Evento | Ramas | Motivo |
| --- | --- | --- |
| `push` | `main`, `desarrollo` | Validar lo que se integró |
| `pull_request` | hacia `main` | Bloquear la fusión si algo falla |
| Manual | cualquiera | Reejecutar sin generar un commit vacío |

Hay una regla de concurrencia por rama.
En caso de que lleguen varios envíos seguidos, se cancela la ejecución anterior, puesto que no tiene sentido gastar minutos de cómputo validando un commit que ya quedó superado.

---

## Etapas

```
                     ┌──────────────────────────┐
                     │  1. verificacion_rapida  │   ~1 min
                     │  Estilo, YAML, JSON      │
                     └────────────┬─────────────┘
                                  │
                ┌─────────────────┴─────────────────┐
                v                                   v
   ┌─────────────────────────┐      ┌──────────────────────────────┐
   │  2. pruebas_unitarias   │      │ 3. validar_infraestructura   │
   │  Python 3.11 y 3.12     │      │ compose y construcción       │
   │  ~3 min                 │      │ ~8 min                       │
   └────────────┬────────────┘      └──────────────┬───────────────┘
                └─────────────────┬────────────────┘
                                  v
                  ┌────────────────────────────────┐
                  │  4. prueba_de_integracion      │   ~6 min
                  │  Pipeline y dbt sobre Postgres │
                  └────────────────┬───────────────┘
                                   v
                  ┌────────────────────────────────┐
                  │  5. resumen                    │
                  │  Consolida y decide el estado  │
                  └────────────────────────────────┘
```

### Etapa 1. Verificaciones rápidas

La primera etapa corre en aproximadamente un minuto y atrapa los errores más comunes.

- **Estilo del código** con ruff, configurado en `pyproject.toml`.
  Los conjuntos de reglas seleccionados son los que atrapan errores reales, es decir, variables sin usar, importaciones muertas, fallas lógicas frecuentes y sintaxis obsoleta.
- **Formato** con `ruff format --check`.
  Está marcado para no bloquear, porque un desajuste de formato no justifica frenar una entrega.
- **Validez de los YAML.**
  La revisión recorre todos los archivos del repositorio excluyendo entornos virtuales y artefactos, y usa `safe_load_all` porque algunos archivos traen varios documentos.
- **Validez del JSON del tablero de Grafana.**
  Un tablero mal formado se detecta aquí y no cuando alguien abre Grafana y ve un panel vacío.

### Etapa 2. Pruebas unitarias

La segunda etapa corre la batería completa sobre Python 3.11 y 3.12.

Conviene precisar que se usa `fail-fast: false` a propósito.
La razón es que, si una versión falla, interesa ver también el resultado de la otra para saber si el problema es general o específico de esa versión.
Con la configuración por defecto, en cambio, la primera falla cancelaría el resto y esa información se perdería.

Las variables `METRICAS_HABILITADAS` y `PUSHGATEWAY_URL` se fijan para que las pruebas no intenten conectarse a un Pushgateway que no existe en el entorno de integración.

Los resultados y la cobertura se guardan como artefactos con retención de catorce días, de manera que se puedan comparar entre corridas cuando algo se degrada de a poco.

### Etapa 3. Validación de la infraestructura

La tercera etapa valida que la infraestructura definida como código es correcta.

- `docker compose config --quiet` comprueba la sintaxis y que todas las referencias entre servicios existan.
- Adicionalmente, se construyen las dos imágenes del proyecto.
  Cabe señalar que un Dockerfile que no compila es un problema que hay que descubrir en la integración y no cuando alguien intenta levantar el entorno.
- Por último, se verifica que la imagen de Spark funciona importando PySpark dentro del contenedor recién construido.

La caché de capas de GitHub baja el tiempo de esta etapa de varios minutos a menos de uno cuando los Dockerfiles no cambiaron.

### Etapa 4. Prueba de integración

La cuarta etapa es la que más se parece a una corrida real, porque levanta un PostgreSQL de verdad como servicio del trabajo y ejecuta el flujo completo contra él.

1. Crea los tres esquemas del almacén.
2. Corre el pipeline sobre la muestra versionada.
3. Verifica que los archivos esperados existen.
4. Instala dbt, resuelve sus dependencias y construye los modelos.
5. Corre las pruebas de datos de dbt.

La entrada empleada es la muestra de cincuenta mil filas y no el archivo completo.
El motivo es que descargar noventa y seis megabytes en cada corrida de integración agregaría un minuto sin aportar cobertura adicional, puesto que la lógica es la misma.

Los artefactos que quedan guardados incluyen el reporte de la corrida, el CSV del agregado y el directorio `target` de dbt, que contiene el manifiesto y los resultados de cada prueba.

### Etapa 5. Resumen

La última etapa escribe una tabla en el resumen de la ejecución de GitHub con el resultado de cada una de las anteriores, y falla si alguna no pasó.

Corre siempre, incluso cuando una etapa anterior falló, porque justamente ahí es cuando el resumen resulta más útil.

---

## Qué falta para tener entrega continua

El flujo actual es de integración continua, de modo que valida pero no despliega.
A continuación se describen las etapas que faltarían, en el orden en que tendría sentido agregarlas.

### Publicación de imágenes

```yaml
publicar_imagenes:
  needs: prueba_de_integracion
  if: github.ref == 'refs/heads/main'
  permissions:
    packages: write
  steps:
    - uses: docker/login-action@v3
      with:
        registry: ghcr.io
        username: ${{ github.actor }}
        password: ${{ secrets.GITHUB_TOKEN }}
    - uses: docker/build-push-action@v6
      with:
        push: true
        tags: |
          ghcr.io/${{ github.repository }}/airflow:${{ github.sha }}
          ghcr.io/${{ github.repository }}/airflow:latest
```

El etiquetado con el identificador del commit es lo que permite saber exactamente qué código está corriendo en cada entorno y volver atrás sin ambigüedad.

### Despliegue a un entorno de pruebas

Sería automático al integrar en `main`, sin aprobación manual.
Dicho de otro modo, la red de contención son las pruebas y no una persona revisando.

### Despliegue a producción

Sería con aprobación manual mediante los entornos protegidos de GitHub.
El razonamiento es que un despliegue a producción debería requerir que alguien mire lo que se está por publicar.

### Migraciones del almacén

Los modelos de dbt se materializan de cero en cada construcción, de manera que ahí no hay migraciones.
Lo que sí las necesitaría son los cambios de esquema en la zona cruda, con una herramienta que registre qué migración ya se aplicó.

### Reversión

La estrategia más simple consiste en volver a desplegar la imagen del commit anterior.
Puesto que las imágenes están etiquetadas con el identificador del commit, revertir se reduce a cambiar una etiqueta.

Para los datos, en cambio, la reversión es más delicada.
La escritura es de reemplazo completo, así que una vez sobrescrito el resultado no hay vuelta atrás sin una copia de seguridad.
Tal limitación constituye el argumento más fuerte para pasar a carga incremental por partición.

---

## Ejecutar las mismas verificaciones en local

Conviene correr lo mismo antes de enviar, para no descubrir un problema de estilo después de esperar la integración.

```bash
make verificar
```

Dicho objetivo equivale a los dos comandos siguientes.

```bash
python -m ruff check trabajos pruebas orquestacion scripts ejecutar_pipeline.py
python -m pytest pruebas -v
```

Para la parte de infraestructura se usan estos otros dos.

```bash
docker compose config --quiet
docker compose build
```

---

## Tiempos aproximados

| Etapa | Con caché | Sin caché |
| --- | --- | --- |
| Verificaciones rápidas | 40 s | 1 min |
| Pruebas unitarias | 2 min | 3 min |
| Infraestructura | 50 s | 8 min |
| Integración | 5 min | 6 min |
| **Total** | **~7 min** | **~15 min** |

Las etapas 2 y 3 corren en paralelo, motivo por el cual el total es menor que la suma.
