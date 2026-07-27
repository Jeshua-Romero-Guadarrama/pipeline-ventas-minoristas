"""
El presente subpaquete reúne los trabajos de procesamiento distribuido con PySpark.
La separación respecto del resto del paquete es deliberada, puesto que los módulos de pandas se importan en cualquier proceso sin costo apreciable, mientras que importar PySpark levanta una máquina virtual de Java y agrega varios segundos al arranque.
De ese modo, quien solo necesita la lógica de negocio no paga ese precio.
"""
