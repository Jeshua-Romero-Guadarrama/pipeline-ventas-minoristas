{#
    Sobrescribe el comportamiento por defecto de dbt para nombrar los esquemas.

    Sin esta macro, dbt concatena el esquema del perfil con el que define el modelo y termina creando algo como publicado_preparado, que no es lo que se declaró en el proyecto ni lo que espera quien escribe una consulta.

    Con la macro, en cambio, el esquema declarado en dbt_project.yml se usa tal cual.
    En caso de que un modelo no declare ninguno, la macro cae en el esquema del perfil.
#}

{% macro generate_schema_name(custom_schema_name, node) -%}

    {%- set esquema_por_defecto = target.schema -%}

    {%- if custom_schema_name is none -%}
        {{ esquema_por_defecto }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}

{%- endmacro %}


{#
    Convierte un importe a decimal con dos posiciones.

    La conversión se repite en casi todos los modelos, motivo por el cual conviene tenerla centralizada.
    De ese modo se evita que en algún lugar se escriba una escala distinta y los totales dejen de cerrar entre capas por una diferencia de redondeo.
#}

{% macro a_importe(columna) -%}
    round(cast({{ columna }} as numeric), 2)
{%- endmacro %}


{#
    Divide protegiendo el cálculo contra el denominador en cero.

    En SQL, una división por cero corta toda la consulta.
    En cambio, devolver nulo resulta mucho más útil, porque el resto del modelo se construye igual y el vacío queda visible en el tablero.
#}

{% macro division_segura(numerador, denominador) -%}
    case
        when coalesce({{ denominador }}, 0) = 0 then null
        else cast({{ numerador }} as numeric) / cast({{ denominador }} as numeric)
    end
{%- endmacro %}
