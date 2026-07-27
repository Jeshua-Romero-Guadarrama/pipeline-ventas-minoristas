# Certificados de confianza adicionales

La presente carpeta existe para un caso muy concreto.
En algunas redes, las conexiones salientes se interceptan y se vuelven a firmar con un certificado propio de la organización.
El sistema anfitrión confía en ese certificado porque lo tiene instalado, mientras que los contenedores no, motivo por el cual cualquier descarga de paquetes dentro de la construcción de la imagen falla con el mensaje siguiente.

```
SSLError(SSLCertVerificationError(1, '[SSL: CERTIFICATE_VERIFY_FAILED]
certificate verify failed: unable to get local issuer certificate'))
```

## Cómo se resuelve

A continuación, se coloca en esta carpeta el certificado raíz de la entidad que intercepta, con extensión `.crt` y en formato PEM.
Los Dockerfiles del proyecto lo detectan solos, lo copian al almacén de confianza del contenedor y ejecutan `update-ca-certificates`.
En caso de que la carpeta esté vacía, el paso no hace nada, de manera que el proyecto funciona sin cambios en una red que no intercepta.

## Cómo obtener el certificado

Para averiguar si hay interceptación y quién la hace, basta con inspeccionar la cadena de certificados desde un contenedor.

```bash
docker run --rm python:3.12-slim-bookworm sh -c \
  "apt-get update -qq && apt-get install -y -qq openssl && \
   echo | openssl s_client -connect pypi.org:443 2>/dev/null | grep 'i:'"
```

Siempre que el emisor no sea una autoridad pública conocida, hay interceptación.
En ese caso, el certificado raíz correspondiente se exporta desde el almacén de confianza del sistema anfitrión y se guarda aquí.

## Por qué los archivos no se versionan

El `.gitignore` excluye los `.crt` de esta carpeta.
Al respecto, un certificado de este tipo pertenece a la infraestructura de quien lo emite, no aporta nada a quien clone el repositorio desde otra red y no corresponde publicarlo.
Lo que sí se versiona es el mecanismo, es decir, la carpeta y el paso del Dockerfile que la consume, de modo que resolver el problema quede en copiar un archivo.
