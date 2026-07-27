/*
    Comprueba que las participaciones del ranking están bien calculadas.

    Al respecto, se verifican tres condiciones.
    En primer lugar, ninguna participación individual puede quedar fuera del rango de cero a cien.
    A continuación, la participación acumulada tampoco puede salirse de ese rango.
    Por último, la acumulada de cada fila tiene que ser mayor o igual que la de la fila anterior, dado que una suma de valores positivos no puede decrecer.

    Un error de este tipo pasaría inadvertido en el tablero, puesto que los porcentajes se ven plausibles aunque estén mal ordenados.
*/

with ranking as (

    select
        posicion,
        producto_id,
        participacion_porcentual,
        participacion_acumulada,
        lag(participacion_acumulada) over (order by posicion) as acumulada_anterior

    from {{ ref('pub_ranking_productos') }}

),

incoherencias as (

    select
        posicion,
        producto_id,
        participacion_porcentual,
        participacion_acumulada,
        acumulada_anterior,
        case
            when participacion_porcentual < 0 or participacion_porcentual > 100
                then 'participacion individual fuera de rango'
            when participacion_acumulada < 0 or participacion_acumulada > 100.01
                then 'participacion acumulada fuera de rango'
            when acumulada_anterior is not null
                 and participacion_acumulada < acumulada_anterior
                then 'la participacion acumulada decrece'
        end                                                  as motivo

    from ranking

)

select *
from incoherencias
where motivo is not null
