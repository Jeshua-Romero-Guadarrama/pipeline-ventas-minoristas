/*
    Comprueba que la serie diaria concuerda con el detalle día por día.

    La prueba de los totales entre capas compara un único total general, y eso deja pasar un caso incómodo.
    En caso de que un día quede de más y otro de menos por la misma cifra, el total general cierra igual aunque la serie temporal esté mal.
    Por ello la presente prueba baja la comparación al nivel de cada día y descarta esa situación.
*/

with detalle_por_dia as (

    select
        fecha_venta                                     as fecha,
        round(cast(sum(ingreso_linea) as numeric), 2)   as importe

    from {{ ref('prep_ventas') }}
    group by fecha_venta

),

resumen as (

    select
        fecha,
        round(cast(ingreso_total as numeric), 2)        as importe

    from {{ ref('pub_resumen_diario') }}

),

comparacion as (

    select
        coalesce(detalle_por_dia.fecha, resumen.fecha)  as fecha,
        detalle_por_dia.importe                         as importe_detalle,
        resumen.importe                                 as importe_resumen,
        abs(
            coalesce(detalle_por_dia.importe, 0) - coalesce(resumen.importe, 0)
        )                                               as diferencia

    -- La unión completa detecta también los días que existen en una tabla y faltan en la otra, que un cruce interno dejaría pasar sin aviso.
    from detalle_por_dia
    full outer join resumen
        on detalle_por_dia.fecha = resumen.fecha

)

select *
from comparacion
where diferencia > {{ var('tolerancia_importes') }}
