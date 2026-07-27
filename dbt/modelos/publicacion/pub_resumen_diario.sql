/*
    Serie temporal diaria del negocio.

    El presente modelo alimenta los gráficos de tendencia.
    La agregación parte del detalle y no del modelo de producto y fecha, porque contar clientes o facturas distintas sobre un agregado daría un número inflado.
    Conviene precisar que los conteos de valores distintos no se pueden sumar entre grupos.

    Adicionalmente, se incluye una media móvil de siete días.
    Puesto que el comercio tiene un patrón semanal muy marcado, con casi nada de facturación los sábados, sin suavizar la serie el gráfico queda como un puro diente de sierra.
*/

{{
    config(
        materialized = 'table',
        tags = ['publicacion', 'tendencia'],
        indexes = [
            {'columns': ['fecha'], 'unique': true}
        ]
    )
}}

with ventas as (

    select * from {{ ref('int_ventas_enriquecidas') }}

),

por_dia as (

    select
        fecha_venta                                          as fecha,

        {{ a_importe('sum(ingreso_linea)') }}                as ingreso_total,
        sum(unidades)                                        as unidades_vendidas,
        count(*)                                             as lineas_de_factura,
        count(distinct numero_factura)                       as facturas_distintas,
        count(distinct codigo_producto)                      as productos_distintos,
        count(distinct identificador_cliente)                as clientes_distintos,
        count(distinct pais)                                 as paises_distintos,

        max(anio)                                            as anio,
        max(mes)                                             as mes,
        max(anio_mes)                                        as anio_mes,
        max(dia_de_semana)                                   as dia_de_semana,
        bool_or(es_fin_de_semana)                            as es_fin_de_semana,

        {{ a_importe('sum(case when es_concepto_administrativo then ingreso_linea else 0 end)') }}
            as ingreso_administrativo

    from ventas
    group by fecha_venta

),

con_ratios as (

    select
        por_dia.*,

        {{ a_importe(division_segura('ingreso_total', 'facturas_distintas')) }}
            as ticket_promedio,

        {{ a_importe(division_segura('ingreso_total', 'productos_distintos')) }}
            as ingreso_promedio_por_producto,

        {{ a_importe(division_segura('unidades_vendidas', 'facturas_distintas')) }}
            as unidades_promedio_por_factura

    from por_dia

),

con_tendencia as (

    select
        con_ratios.*,

        -- La media móvil abarca los siete días anteriores, incluido el actual.
        -- La ventana se define por filas y no por rango de fechas, dado que el modelo ya tiene una fila por cada día con venta, que es justamente la serie que interesa suavizar.
        {{ a_importe('avg(ingreso_total) over (order by fecha rows between 6 preceding and current row)') }}
            as ingreso_media_movil_7d,

        {{ a_importe('sum(ingreso_total) over (order by fecha rows between unbounded preceding and current row)') }}
            as ingreso_acumulado,

        -- La variación se calcula contra el día anterior con venta.
        -- De ese modo se detectan los saltos bruscos, que suelen indicar un problema de carga.
        {{ a_importe('ingreso_total - lag(ingreso_total) over (order by fecha)') }}
            as variacion_contra_dia_anterior

    from con_ratios

)

select * from con_tendencia
order by fecha
