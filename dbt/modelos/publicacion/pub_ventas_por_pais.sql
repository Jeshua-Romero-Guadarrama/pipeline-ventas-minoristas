/*
    Distribución geográfica de la facturación.

    El comercio de origen es británico y vende sobre todo en su mercado local.
    No obstante, tiene una porción de exportación que conviene medir por separado.
    De ese modo, el modelo permite responder qué mercados sostienen el negocio y cuáles resultan marginales.
*/

{{
    config(
        materialized = 'table',
        tags = ['publicacion', 'geografia'],
        indexes = [
            {'columns': ['pais'], 'unique': true}
        ]
    )
}}

with ventas as (

    select * from {{ ref('int_ventas_enriquecidas') }}

),

por_pais as (

    select
        pais,

        {{ a_importe('sum(ingreso_linea)') }}                as ingreso_total,
        sum(unidades)                                        as unidades_vendidas,
        count(*)                                             as lineas_de_factura,
        count(distinct numero_factura)                       as facturas_distintas,
        count(distinct codigo_producto)                      as productos_distintos,
        count(distinct identificador_cliente)                as clientes_distintos,
        count(distinct fecha_venta)                          as dias_con_venta,

        min(fecha_venta)                                     as primera_venta,
        max(fecha_venta)                                     as ultima_venta

    from ventas
    group by pais

),

con_participacion as (

    select
        por_pais.*,

        row_number() over (order by ingreso_total desc)      as posicion,

        {{ a_importe(division_segura('ingreso_total', 'facturas_distintas')) }}
            as ticket_promedio,

        round(
            cast(
                {{ division_segura('ingreso_total', 'sum(ingreso_total) over ()') }} * 100
            as numeric),
            4
        )                                                    as participacion_porcentual,

        case
            when pais = 'UNITED KINGDOM' then 'mercado local'
            when pais = 'DESCONOCIDO'    then 'sin identificar'
            else 'exportacion'
        end                                                  as tipo_de_mercado

    from por_pais

)

select * from con_participacion
order by posicion
