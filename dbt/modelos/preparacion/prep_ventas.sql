/*
    Capa de preparación del detalle de ventas.

    La presente vista es la única puerta de entrada al dato crudo, dado que todo lo que viene después consulta acá y nunca la tabla de origen.
    En caso de que mañana cambie el formato del archivo, o de que el pipeline agregue una columna, el ajuste se hace en el presente archivo y el resto del proyecto no se entera.

    Acá solo hay normalización, es decir tipos, nombres y limpieza de texto.
    La lógica de negocio, en cambio, vive en la capa intermedia (mezclar ambas cosas es justamente lo que vuelve inmantenible un proyecto de SQL).
*/

{{
    config(
        materialized = 'view',
        tags = ['preparacion', 'ventas']
    )
}}

with origen as (

    select * from {{ source('crudo', 'detalle_ventas') }}

),

normalizado as (

    select
        -- En los identificadores se recortan los espacios y se unifica todo a mayúsculas, puesto que el archivo de origen es inconsistente en ese punto.
        upper(trim(factura))                                as numero_factura,
        upper(trim(producto_id))                            as codigo_producto,
        nullif(trim(descripcion), '')                       as descripcion_producto,
        upper(trim(coalesce(pais, 'DESCONOCIDO')))          as pais,
        cast(cliente_id as bigint)                          as identificador_cliente,

        -- La columna de fecha llega como marca de tiempo, y acá se separa el día del instante exacto.
        -- Al respecto, se trata de dos granularidades distintas y conviene tenerlas explícitas.
        cast(fecha as date)                                 as fecha_venta,
        cast(fecha_hora as timestamp)                       as momento_venta,

        -- En las medidas, el importe pasa a decimal con escala fija porque el punto flotante acumula error al sumar cientos de miles de filas.
        cast(cantidad as integer)                           as unidades,
        {{ a_importe('precio_unitario') }}                  as precio_unitario,
        {{ a_importe('ingreso_total') }}                    as ingreso_linea

    from origen

),

marcado as (

    select
        normalizado.*,

        -- Los códigos que no siguen el patrón numérico habitual corresponden a conceptos administrativos, como los envíos o los ajustes manuales.
        -- En consecuencia, se los marca en lugar de eliminarlos, de manera que cada consulta decida si los quiere.
        case
            when codigo_producto ~ '^[0-9]{5}' then false
            else true
        end                                                 as es_concepto_administrativo,

        case
            when identificador_cliente is null then true
            else false
        end                                                 as es_venta_sin_cliente

    from normalizado

)

select * from marcado
