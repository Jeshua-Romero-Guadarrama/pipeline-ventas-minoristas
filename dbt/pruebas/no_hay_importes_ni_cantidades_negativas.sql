/*
    Comprueba que ningún modelo publicado tiene medidas negativas.

    Puesto que el pipeline aparta las devoluciones antes de agregar, a esta altura un importe o una cantidad negativa solo puede venir de un error de cálculo.
    Por ello la prueba recorre los tres modelos finales y devuelve el detalle de lo que encuentre, de manera que nadie tenga que buscar dónde está el problema.
*/

with ingresos_por_producto as (

    select
        'pub_ingresos_producto_fecha'   as modelo,
        producto_id                     as clave,
        ingreso_total,
        unidades_vendidas

    from {{ ref('pub_ingresos_producto_fecha') }}
    where ingreso_total < 0
       or unidades_vendidas < 0

),

resumen_diario as (

    select
        'pub_resumen_diario'            as modelo,
        cast(fecha as varchar)          as clave,
        ingreso_total,
        unidades_vendidas

    from {{ ref('pub_resumen_diario') }}
    where ingreso_total < 0
       or unidades_vendidas < 0

),

ranking as (

    select
        'pub_ranking_productos'         as modelo,
        producto_id                     as clave,
        ingreso_total,
        unidades_vendidas

    from {{ ref('pub_ranking_productos') }}
    where ingreso_total < 0
       or unidades_vendidas < 0

)

select * from ingresos_por_producto
union all
select * from resumen_diario
union all
select * from ranking
