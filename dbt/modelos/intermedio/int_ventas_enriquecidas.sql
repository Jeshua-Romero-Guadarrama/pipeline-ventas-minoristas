/*
    Capa intermedia con los atributos derivados que comparten los modelos finales.

    Todo lo que se calcula acá se usa en más de un modelo de publicación, y ese es el criterio para que algo viva en esta capa.
    En caso de que un cálculo lo use un solo modelo, va directamente en ese modelo, puesto que una capa intermedia con cálculos de un único consumidor solo agrega indirección sin ninguna ganancia.
*/

{{
    config(
        materialized = 'view',
        tags = ['intermedio', 'ventas']
    )
}}

with ventas as (

    select * from {{ ref('prep_ventas') }}

),

con_calendario as (

    select
        ventas.*,

        -- Los atributos de calendario se guardan como columnas para evitar que cada consulta del tablero los extraiga con funciones de fecha.
        -- Conviene precisar que ese uso de funciones impide aprovechar los índices en las tablas grandes.
        extract(year   from fecha_venta)::integer            as anio,
        extract(month  from fecha_venta)::integer            as mes,
        extract(day    from fecha_venta)::integer            as dia,
        extract(dow    from fecha_venta)::integer            as dia_de_semana,
        extract(hour   from momento_venta)::integer          as hora_del_dia,
        to_char(fecha_venta, 'YYYY-MM')                      as anio_mes,
        date_trunc('month', fecha_venta)::date               as primer_dia_del_mes,
        date_trunc('week',  fecha_venta)::date               as primer_dia_de_semana,

        case
            when extract(dow from fecha_venta) in (0, 6) then true
            else false
        end                                                  as es_fin_de_semana,

        -- La franja horaria comercial divide la jornada en cuatro tramos.
        -- Dado que el comercio de origen concentra casi toda su facturación entre las diez y las quince, separar la jornada ayuda a leer los patrones de compra.
        case
            when extract(hour from momento_venta) < 10 then 'temprano'
            when extract(hour from momento_venta) < 13 then 'media manana'
            when extract(hour from momento_venta) < 16 then 'media tarde'
            else 'tarde'
        end                                                  as franja_horaria

    from ventas

),

con_segmento as (

    select
        con_calendario.*,

        -- Los dos bloques siguientes segmentan la línea de venta por su tamaño.
        -- Cabe señalar que los cortes salen de mirar la distribución real del conjunto de datos, donde la mediana ronda las diez libras y la cola larga arranca cerca de las cien.
        case
            when ingreso_linea < 5    then 'muy baja'
            when ingreso_linea < 20   then 'baja'
            when ingreso_linea < 100  then 'media'
            when ingreso_linea < 500  then 'alta'
            else 'muy alta'
        end                                                  as segmento_importe,

        case
            when unidades = 1         then 'unitaria'
            when unidades <= 12       then 'minorista'
            when unidades <= 100      then 'mayorista'
            else 'volumen'
        end                                                  as segmento_volumen

    from con_calendario

)

select * from con_segmento
