/*
    Modelo principal del proyecto y respuesta directa al objetivo del enunciado.

    El resultado tiene una fila por cada combinación de fecha y producto, con el ingreso total del día.
    Junto al ingreso se publican medidas de apoyo que ayudan a interpretarlo, dado que el ingreso por sí solo no distingue un producto caro que se vende poco de uno barato que se vende mucho.

    El modelo se materializa como tabla porque los tableros lo consultan constantemente y recalcular el agregado en cada consulta sería un desperdicio.
*/

{{
    config(
        materialized = 'table',
        tags = ['publicacion', 'principal'],
        indexes = [
            {'columns': ['fecha'], 'type': 'btree'},
            {'columns': ['producto_id'], 'type': 'btree'},
            {'columns': ['fecha', 'producto_id'], 'unique': true}
        ]
    )
}}

with ventas as (

    select * from {{ ref('int_ventas_enriquecidas') }}

),

agregado as (

    select
        fecha_venta                                          as fecha,
        codigo_producto                                      as producto_id,

        -- La medida que sigue es la central del modelo y la que pide el enunciado.
        {{ a_importe('sum(ingreso_linea)') }}                as ingreso_total,

        -- A continuación vienen las medidas de apoyo que permiten interpretar el ingreso.
        sum(unidades)                                        as unidades_vendidas,
        count(*)                                             as lineas_de_factura,
        count(distinct numero_factura)                       as facturas_distintas,
        count(distinct identificador_cliente)                as clientes_distintos,
        {{ a_importe('avg(precio_unitario)') }}              as precio_unitario_promedio,
        {{ a_importe('min(precio_unitario)') }}              as precio_unitario_minimo,
        {{ a_importe('max(precio_unitario)') }}              as precio_unitario_maximo,

        -- Los atributos siguientes no cambian dentro del grupo, motivo por el cual se los arrastra con una función de agregación cualquiera.
        max(anio)                                            as anio,
        max(mes)                                             as mes,
        max(anio_mes)                                        as anio_mes,
        bool_or(es_fin_de_semana)                            as es_fin_de_semana,
        bool_or(es_concepto_administrativo)                  as es_concepto_administrativo,

        -- La descripción se toma como la más frecuente, puesto que el mismo código aparece con textos ligeramente distintos según quién lo cargó.
        mode() within group (order by descripcion_producto)  as descripcion_producto,
        mode() within group (order by pais)                  as pais_predominante

    from ventas
    group by
        fecha_venta,
        codigo_producto

),

con_derivadas as (

    select
        agregado.*,

        -- La derivada siguiente es el ingreso medio por factura del producto en ese día.
        -- Al respecto, constituye la medida que mejor refleja cuánto aporta el producto a cada operación de venta.
        {{ a_importe(division_segura('ingreso_total', 'facturas_distintas')) }}
            as ingreso_promedio_por_factura,

        {{ a_importe(division_segura('ingreso_total', 'unidades_vendidas')) }}
            as ingreso_promedio_por_unidad

    from agregado

)

select * from con_derivadas
order by fecha, ingreso_total desc
