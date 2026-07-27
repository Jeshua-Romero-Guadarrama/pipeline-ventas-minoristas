/*
    Ranking de productos por ingreso acumulado en todo el período.

    Además del total, el modelo trae la participación de cada producto y la acumulada, que es lo que permite responder cuántos artículos explican el ochenta por ciento de la facturación.
    Cabe señalar que en este conjunto de datos la concentración es fuerte y esa pregunta aparece siempre.

    La cantidad de posiciones sale de una variable del proyecto, de modo que se ajusta al invocar dbt sin necesidad de editar el modelo.
*/

{{
    config(
        materialized = 'table',
        tags = ['publicacion', 'ranking'],
        indexes = [
            {'columns': ['posicion'], 'unique': true},
            {'columns': ['producto_id'], 'unique': true}
        ]
    )
}}

with ventas as (

    select * from {{ ref('int_ventas_enriquecidas') }}

),

por_producto as (

    select
        codigo_producto                                      as producto_id,
        mode() within group (order by descripcion_producto)  as descripcion_producto,

        {{ a_importe('sum(ingreso_linea)') }}                as ingreso_total,
        sum(unidades)                                        as unidades_vendidas,
        count(distinct numero_factura)                       as facturas_distintas,
        count(distinct fecha_venta)                          as dias_con_venta,
        count(distinct identificador_cliente)                as clientes_distintos,
        count(distinct pais)                                 as paises_distintos,

        min(fecha_venta)                                     as primera_venta,
        max(fecha_venta)                                     as ultima_venta,

        {{ a_importe('avg(precio_unitario)') }}              as precio_unitario_promedio,
        bool_or(es_concepto_administrativo)                  as es_concepto_administrativo

    from ventas
    group by codigo_producto

),

con_total_general as (

    select
        por_producto.*,
        sum(ingreso_total) over ()                           as ingreso_general

    from por_producto

),

con_participacion as (

    select
        producto_id,
        descripcion_producto,
        ingreso_total,
        unidades_vendidas,
        facturas_distintas,
        dias_con_venta,
        clientes_distintos,
        paises_distintos,
        primera_venta,
        ultima_venta,
        precio_unitario_promedio,
        es_concepto_administrativo,

        row_number() over (order by ingreso_total desc)      as posicion,

        round(
            cast({{ division_segura('ingreso_total', 'ingreso_general') }} * 100 as numeric),
            4
        )                                                    as participacion_porcentual,

        round(
            cast(
                sum({{ division_segura('ingreso_total', 'ingreso_general') }})
                    over (order by ingreso_total desc rows between unbounded preceding and current row)
                * 100
            as numeric),
            4
        )                                                    as participacion_acumulada,

        {{ a_importe(division_segura('ingreso_total', 'dias_con_venta')) }}
            as ingreso_promedio_diario

    from con_total_general

)

select *
from con_participacion
where posicion <= {{ var('productos_en_ranking') }}
order by posicion
