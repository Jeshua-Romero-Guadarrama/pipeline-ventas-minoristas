/*
    Comprueba que agregar no crea ni pierde dinero.

    La presente prueba es la más importante del proyecto, dado que el detalle de ventas y el modelo agregado por producto y fecha tienen que sumar exactamente lo mismo.
    En caso de que un día no coincidan, en algún punto de la cadena se duplicaron o se perdieron filas.
    Cabe señalar que se trata de la clase de error que pasa desapercibido durante semanas, porque el tablero sigue mostrando números que parecen razonables.

    Una prueba de dbt falla cuando devuelve al menos una fila, motivo por el cual la consulta está escrita para devolver algo solo cuando hay un problema.

    Al respecto, se admite una diferencia de un centavo por el redondeo acumulado, que resulta inevitable al sumar cientos de miles de importes con dos decimales.
*/

with total_del_detalle as (

    select
        round(cast(sum(ingreso_linea) as numeric), 2) as importe

    from {{ ref('prep_ventas') }}

),

total_del_agregado as (

    select
        round(cast(sum(ingreso_total) as numeric), 2) as importe

    from {{ ref('pub_ingresos_producto_fecha') }}

),

comparacion as (

    select
        total_del_detalle.importe        as importe_detalle,
        total_del_agregado.importe       as importe_agregado,
        abs(total_del_detalle.importe - total_del_agregado.importe) as diferencia

    from total_del_detalle
    cross join total_del_agregado

)

select *
from comparacion
where diferencia > {{ var('tolerancia_importes') }}
