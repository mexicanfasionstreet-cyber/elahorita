# Marca de El Ahorita

Aquí van los archivos de identidad. El programa los toma solos: si están, se usan;
si no, cae al sello de texto y al ámbar por defecto.

## Archivos que leo

| Archivo | Para qué | Formato |
|---|---|---|
| `logo.png` | Sello en la esquina inferior izquierda de cada diapositiva | PNG con transparencia, blanco o claro (va sobre foto oscurecida), ~4:1 horizontal, mínimo 400 px de ancho |
| `logo-cierre.png` | Logo completo para la tarjeta final (opcional) | PNG con transparencia, puede incluir la bajada de marca |
| `ajustes.json` | Colores y textos | ver abajo |

Si prefieres otro nombre de archivo, se cambia en `ajustes.json` con la ruta.

## ajustes.json

```json
{
  "sello": "EL AHORITA",
  "acento": "#FFB020",
  "logo": "marca/logo.png"
}
```

- **`sello`**: texto que aparece si no hay logo.
- **`acento`**: color del recuadro de la sección y de la rayita sobre el sello, en hex.
- **`logo`**: ruta al logo desde la raíz del proyecto.

## Qué NO cambia solo

El tamaño y la posición del titular (1080×1920, márgenes de 72 px, titular abajo).
Eso está en `capsula.py`, en las constantes `ANCHO`, `ALTO`, `MARGEN` y en
`diapositiva()`. Si tu manual de marca pide otro sitio, se ajusta ahí.

Las fuentes son Segoe UI Black / Bold de Windows. Si la marca usa otra
tipografía, pásame el `.ttf` o `.otf` a esta carpeta y lo enlazo.
