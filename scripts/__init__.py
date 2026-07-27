"""
Utilidades de línea de comandos que acompañan al proyecto.
Al respecto, son herramientas de apoyo que no forman parte del pipeline en sí.
Asimismo, se agrupan como paquete con el fin de poder invocarlas con la opción de módulo de Python, que resuelve las importaciones relativas sin depender del directorio desde el que se ejecuta.

    python -m scripts.generar_documento_entrega

El paquete reúne cuatro módulos.
En primer lugar, descargar_dataset baja el histórico completo desde el origen.
A continuación, generar_muestra arma la muestra versionada que viaja en el repositorio.
Por su parte, generar_documento_entrega construye el documento de entrega en formato Word.
Por último, contenido_entrega reúne el texto de las secciones de ese documento.
"""
