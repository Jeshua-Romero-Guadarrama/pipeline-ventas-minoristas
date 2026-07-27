/*
    Detecta interrupciones sospechosas en la serie diaria.

    El comercio no factura todos los días del calendario, motivo por el cual un hueco de uno o dos días resulta normal, sobre todo en los fines de semana y en los feriados.
    En cambio, un hueco de más de diez días seguidos ya no lo es y suele significar que faltó cargar un archivo.

    La presente prueba se declara con severidad de advertencia y no de error.
    Al respecto, la razón es que el conjunto de datos histórico sí tiene una interrupción real, puesto que el comercio cerró varios días entre diciembre y enero.
    De ahí que hacer fallar toda la construcción por un hecho conocido del negocio resultaría contraproducente.
*/

{{ config(severity = 'warn') }}

with dias as (

    select
        fecha,
        lag(fecha) over (order by fecha) as fecha_anterior

    from {{ ref('pub_resumen_diario') }}

),

huecos as (

    select
        fecha_anterior,
        fecha                            as fecha_siguiente,
        fecha - fecha_anterior           as dias_sin_venta

    from dias
    where fecha_anterior is not null

)

select *
from huecos
where dias_sin_venta > 10
order by dias_sin_venta desc
