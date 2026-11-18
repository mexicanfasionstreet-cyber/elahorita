# El Ahorita

Canal de noticias en YouTube Shorts, **México primero y el mundo como apoyo**. El
robot busca las noticias más relevantes, arma un video vertical de 60-70 s con **1 o 2
notas desarrolladas** —no titulares sueltos— y lo sube **solo**, cuatro veces al día.
Tú solo decides en casos especiales o cuando pides una nota urgente con `/nota`.

Marca: **El Ahorita** · `@ElAhorita` · *Ahorita sí es ahorita.*
Promesa: lo más importante de México y el mundo, en menos de un minuto.

---

## Cómo funciona

```
42 fuentes (directas + espejos de Google News)
        │
        ├─ agrupa la misma historia de varios medios  →  cobertura
        ├─ puntúa: cobertura × peso × recencia × pico de entidad × sección
        └─ se queda con la ventana de la franja y no repite lo ya publicado
                    │
      ┌─────────────┴───────────────────────┐
      │                                     │
  caso normal                  2+ notas de alto impacto
  publica solo                 te pregunta por Telegram
      │                        (30 min; si no, sale la mejor)
      └─────────────┬───────────────────────┘
                    │            tú: /nota <tema o enlace>
        guion con IA + verificador de datos ◄──┘
                    │
        voz (Voicebox con tu voz / edge-tts de respaldo)
        + tiempos por palabra con Whisper
                    │
   video 1080×1920: marca, titular, subtítulos karaoke, cierre
                    │
        sube a YouTube + te manda el video y el enlace al chat
```

### Las cuatro franjas

| Hora (Tijuana) | Qué publica | Ventana de noticias |
|---|---|---|
| 05:00 | Lo que pasó de noche y en la madrugada | desde las 20:00 del día anterior |
| 12:00 | Lo relevante de la mañana | desde las 05:00 |
| 15:00 | Seguimiento o lo nuevo del mediodía | desde las 12:00 |
| 20:00 | El cierre del día | desde las 15:00 |

- **1 o 2 notas por video**: una si gana con claridad (15 % o más); dos si la
  segunda aguanta.
- **Seguimientos**: una historia ya publicada hoy solo vuelve si los medios
  publicaron algo después del video anterior, y el guion cuenta solo lo nuevo.
- **Caso especial**: si 2 o más historias tienen cobertura de alto impacto (peso
  ≥ `ALTO_IMPACTO`, 35 por defecto: casi todas las fuentes a la vez), te pregunta
  cuál sale. Si no contestas en 30 min, publica la mejor. *Ninguna* salta la franja.
- **Si falla**, se reintenta en la siguiente pasada; a la segunda, te avisa.
- **Límite de YouTube**: 6 subidas al día. Las 4 franjas van primero; las otras 2
  quedan para `/nota`.

### Temas sensibles

Suicidio y autolesiones, violencia sexual o menores víctimas, y violencia gráfica
**nunca salen solos**. Si la nota elegida es de uno de esos temas, te pregunta (con una
alternativa) y, si no contestas en 30 min, sale la siguiente no sensible. Lo detectan la
revisión con DeepSeek y una lista de palabras (basta con que una lo marque). En el caso
especial, si no contestas, sale la mejor **no sensible**; las reservas nunca son sensibles.

Todo guion sigue reglas de redacción cuidadosa: sin detalles gráficos; de un suicidio,
nunca el método; de menores víctimas, nada que los identifique; "presunto" para quien no
ha sido sentenciado. Las notas de suicidio cierran con la **Línea de la Vida (800 911
2000)**, que también va en la descripción de YouTube. `/nota` no pregunta (la pediste
tú), pero aplica las mismas reglas.

### La mesa de edición

Telegram es el control remoto. Solo atiende tu chat. Los comandos aparecen en el menú
"/" del chat:

| Comando | Qué hace |
|---|---|
| `/nota <tema o enlace>` | Nota urgente (si cabe en el límite diario) |
| `/notavideo <tema o enlace>` | Igual que `/nota`, pero **no la sube**: te manda el video, el título y la descripción para subirla tú. No gasta cupo |
| `/estado` | Cómo van las franjas de hoy, la próxima, subidas, cupo de `/nota` y si Voicebox responde |
| `/pausa` · `/pausa 3h` · `/pausa 2d` · `/pausa hoy` · `/pausa mañana` | Las franjas no salen (`/nota` sí) |
| `/reanudar` | Quita la pausa |
| `/saltar` · `/saltar noche` | Brinca la próxima franja (o una en concreto) |
| `/ayuda` | La lista |

**Resumen diario**: a partir de las 21:00, cuando cierra la franja de la noche (o a las
22:00), llega lo publicado con sus enlaces, cómo salió cada franja, los avisos del día
(voz de respaldo, fallos, notas cortas), las subidas y cuál sigue.

- **`/nota <tema>`**: busca el tema, elige la historia que **coincide** con lo que
  pediste (no la que más medios tiene), lee hasta 3 artículos y la monta. Si
  nada coincide bien, te ofrece 3 opciones con botones.
- **`/nota <enlace>`**: va directo al artículo, sin búsqueda.
- **`/notavideo`**: misma búsqueda y mismo video, pero no toca YouTube ni el límite
  de 6 subidas. Te llegan el video, el título y la descripción (cada uno en su mensaje,
  para copiarlo) y un botón *Mejor súbelo tú* por si cambias de opinión (ese sí gasta
  cupo). Al subirlo a mano marca en Studio *Contenido alterado o sintético: Sí*.
- **Títulos de YouTube**: el guionista escribe un `titulo` aparte del rótulo de pantalla:
  45–75 caracteres, escritura normal (nombres propios con mayúscula), arranca con lo que
  la gente buscaría y dice qué pasó, sin promesas que el video no cumpla. El verificador
  también lo revisa contra el material.
- **Notas cortas**: si un guion queda en menos de ~45 s, el video te llega pero
  no se sube; tienes el botón *Subir así*.
- **Avisos**: si Voicebox no responde (sale con la voz de respaldo), si faltan
  subtítulos o si una franja falla.

### Alarma (vigilante)

`.github/workflows/vigilante.yml` revisa cada 30 min, con el cron de GitHub (independiente
de cron-job.org, que dispara al robot), que el robot esté corriendo:

- **Sin pasadas en 30 min o más**: lanza una pasada de emergencia y te avisa. Mientras
  cron-job.org no vuelva, el robot sigue corriendo cada ~30 min.
- **3 o más pasadas seguidas fallidas**: te avisa con el enlace al último error.
- El aviso se repite a las 2 h, 6 h y luego cada 12 h mientras siga; cuando se
  recupera, avisa que volvió.

Para probarla: Actions → **Vigilante** → *Run workflow* → "Mandar al chat un mensaje
de prueba".

### Modos de prueba (Actions → El Ahorita → *Run workflow*)

Ninguno sube a YouTube ni guarda estado; el resultado llega a tu chat.

- **Solo probar Voicebox**: conexión, perfil, una frase y un video corto con subtítulos.
- **Probar /nota**: escribe un tema.
- **Probar una franja**: elige madrugada, mañana, tarde o noche.
- **Probar mensajes**: te manda un `/estado` y un resumen del día de ejemplo.

---

## El guion

Lo escribe DeepSeek con reglas duras, y pasa por un **verificador** que caza datos
inventados antes de montar nada.

- 160-185 palabras (~65 s), en español de México, hablado.
- Una o dos notas. La segunda entra solo si aguanta el corte.
- Estructura: gancho → qué pasó → contexto → qué sigue.
- **Prohibido inventar** antecedentes, cargos, fechas o cifras: si el dato no está
  en el material, no se menciona.
- Nunca dice cuántos medios la publican: eso es para el algoritmo, no para el público.

El material no es el titular: se descarga el artículo completo del medio y de ahí sale
todo. Si ningún medio se deja leer, el guion sale corto y **avisa** en vez de rellenar.

---

## El video

| Elemento | Cómo está |
|---|---|
| Formato | 1080×1920, 30 fps, ~65 s, h264 + aac |
| Marca de agua | Tu `overlay-marca-de-agua.png`, arriba a la izquierda |
| Etiqueta | PNG de marca: `● ÚLTIMA HORA` (si tiene ≤3 h y 3+ medios), `AHORITA EN MÉXICO` o `AHORITA EN EL MUNDO` |
| Titular | Caja negra semitransparente, **Anton en mayúsculas**, una línea en rojo, `Fuente:` al pie |
| Subtítulos | Archivo Black 62 px con la **palabra activa en pastilla roja**, sincronizados con `edge-tts`/Voicebox |
| Cierre | Tu `cierre.png` limpio, sin nada encima |
| Fondo | Foto del artículo; si no hay, degradado de marca (negro → rojo) |

Colores: rojo `#E10600`, negro `#0E0E0E`, blanco `#FFFFFF`, gris `#A3A3A3`.
Zonas seguras respetadas: 65 px laterales, 160 arriba, 420 abajo.

---

## La voz

Dos proveedores, **con respaldo automático**:

1. **Voicebox** (tu voz clonada, *Carla-News*) en `http://100.91.104.124:17493`,
   accesible por Tailscale. El runner se une a tu tailnet con `TS_AUTHKEY`.
2. **edge-tts** (`es-MX-DaliaNeural`) si Voicebox no responde. Te avisa por el chat.

La máquina de Voicebox tiene que estar prendida a las horas de las franjas.

---

## Secciones y región

Cada noticia lleva una **sección** (de qué trata; pesa 10 % en el ranking) y una
**región** (dónde pasa; decide la etiqueta del video, *AHORITA EN MÉXICO* o
*EN EL MUNDO*). Las dos salen del contenido, no del medio.

1. **Palabras clave** (`secciones.py`) para las ~1,200 noticias del radar: cada
   sección tiene palabras fuertes y débiles, y el titular pesa más que la entradilla.
2. **Revisión con DeepSeek** de las 25 mejores en cada franja (una sola llamada,
   con caché en `datos/secciones-ia.json`). Si falla, se queda lo de las palabras.

Medido contra 250 noticias reales clasificadas a mano (`herramientas/secciones-oro.json`):

| | Sección | Región |
|---|---|---|
| Clasificador anterior (muestra ciega) | 56 % | 88 % |
| Palabras clave (muestra ciega, antes de ajustar con ella) | 74 % | 98 % |
| DeepSeek (las 250) | 96 % | 100 % |

Para volver a medir: `python herramientas/evaluar-secciones.py --ia`, o en Actions
el modo **Medir secciones**.

## El ranking de relevancia

Señales, todas calculadas con datos que el motor ya produce:

| Señal | Peso | Qué mide |
|---|---|---|
| Cobertura | 40 % | cuántos medios la dan y cuánto pesa cada uno |
| Recencia | 20 % | decae con semivida de 12 h |
| Pico de entidad | 20 % | un personaje que aparece de golpe en muchos titulares |
| Sección | 10 % | seguridad y clima arriba; cultura abajo |
| Tiene foto | 10 % | sin imagen no hay video |

La **agrupación** es por entidades compartidas + tipo de acontecimiento, no por
titular: *"Sheinbaum pide un panda"* y *"Xi y Sheinbaum inauguran…"* son historias
distintas; *"Inhabilitan a Borrego"* en cuatro medios es una sola.

**Diversidad**: dos historias que comparten personaje no salen en el mismo clip.

---

## Fuentes

**42 fuentes verificadas**: 19 directas y 23 espejos de Google News. 25 de México.

- Directas que responden: El País, El País MX, La Jornada, Reforma, 24 Horas,
  López-Dóriga, Zeta Tijuana, Excélsior, El Sol de México, Emeequis, BBC Mundo,
  NYT, Guardian, Al Jazeera, France24, Politico, CNBC.
- Por espejo (bloquean o no tienen RSS): El Universal, Milenio, El Financiero,
  El Economista, Proceso, Animal Político, Sin Embargo, Aristegui, N+, Expansión,
  El Debate, El Informador, El Imparcial, La Silla Rota, SDP, CNN es, DW es,
  Reuters, AP, EFE, Gob.mx.

De cada noticia se **resuelve el enlace** al artículo real (Google News → medio
original) y de ahí salen la foto y la entradilla.

---

## Estructura

```
elahorita/
├── aggregate.py        motor: descarga, limpia, agrupa, clasifica y publica datos
├── relevancia.py       puntuador de relevancia con diversidad
├── guion.py            escribe el guion con IA y lo verifica
├── material.py         saca el texto del artículo (y su og:image)
├── voz.py              audio por segmento + tiempos por palabra
├── subtitulos.py       capa de subtítulos karaoke con transparencia
├── capsula.py          monta el video vertical con la marca
├── publicar.py         sube el Short a YouTube
├── telegram.py         mesa de edición: candidatas, botones, /nota
├── nota.py             nota pedida a mano, de cero a video
├── orquestador.py      decide qué toca en cada pasada
├── config.py           lee .env
├── sources.json        las 42 fuentes verificadas
├── marca/              logos, etiquetas, overlay, cierre y fuentes (Anton, Archivo)
├── herramientas/       probar fuentes, conseguir token de YouTube, estado de claves
├── datos/              corpus, caché de enlaces, estado de Telegram y del orquestador
├── docs/guiones/       el guion de cada clip
├── docs/videos/        los mp4 (no se versionan)
└── .github/workflows/  el robot: cada 5 minutos
```

---

## Comandos

```powershell
# noticias y ranking
python aggregate.py --days 2
python relevancia.py --top 10 --diversidad

# un clip completo
python guion.py --franja manana
python voz.py
python capsula.py
python publicar.py --video docs\videos\X.mp4 --privacidad private

# nota pedida a mano (todo en uno)
python nota.py "Tijuana garita Otay tiempos de espera"

# mesa de edición
python telegram.py --quien        # leer tu chat_id
python telegram.py --candidatas   # mandar las 3 historias del día
python telegram.py --recoger      # leer tu decisión

# el robot
python orquestador.py             # una pasada
python orquestador.py --estado    # qué haría, sin ejecutar
python orquestador.py --franja    # forzar candidatas ahora

# diagnóstico
python herramientas/estado-claves.py
python herramientas/probar-fuentes.py
```

---

## Pruebas

`tests/` tiene las pruebas del robot (pytest). Corren solas en GitHub en cada PR y en
cada push que toque código (workflow **Pruebas**); los commits de estado del robot no
las disparan.

```powershell
pip install -r requirements-dev.txt     # pytest, pillow, numpy (y ffmpeg en el PATH)
python -m pytest                        # todas, ~15 s
python -m pytest -k franjas -q          # solo las de un tema
```

- Nada sale a la red ni toca `datos/`: Telegram, DeepSeek, YouTube, Voicebox y
  Whisper están simulados (`tests/conftest.py`).
- `test_video.py` arma un video de verdad (voz, subtítulos y marca con ffmpeg).
- `test_secciones.py` falla si el clasificador baja de 88 % de sección o 96 % de
  región contra las 250 noticias clasificadas a mano.

## Configuración

Todo va en `.env` (local) y en los secretos del repo. Nunca al código.

| Nombre | Dónde | Para qué |
|---|---|---|
| `DEEPSEEK_API_KEY` | secret | guion y verificación |
| `TELEGRAM_BOT_TOKEN` | secret | mesa de edición |
| `TELEGRAM_CHAT_ID` | secret | tu chat (el único autorizado) |
| `YT_CLIENT_ID` / `YT_CLIENT_SECRET` / `YT_REFRESH_TOKEN` | secrets | subir a YouTube |
| `TS_AUTHKEY` | secret | entrar al tailnet y hablar con Voicebox |
| `YT_PRIVACIDAD` | variable | `private` mientras se prueba, `public` para publicar |
| `VOICEBOX_URL` / `VOICEBOX_PROFILE` | variables | tu voz clonada |

Cada subida a YouTube cuesta **1.600 de 10.000 unidades diarias**: máximo 6 videos
al día. Las 4 franjas caben; las notas extra se descuentan de ahí.

---

## Estado y pendientes

**Funciona**: fuentes, agrupación, ranking, guion verificado, voz, video con marca,
subtítulos karaoke, mesa de Telegram, `/nota`, subida a YouTube en privado y el
disparador confiable cada 5 minutos (cron-job.org).

**Pendiente**:

1. Pasar `YT_PRIVACIDAD` a `public` cuando los videos estén aprobados.
2. Ajustar `ALTO_IMPACTO` con datos reales de días con sucesos grandes.
3. Valorar pedir ampliación de cuota a Google si el canal crece a más de 6 clips/día.
4. Vigilar que el cron siga despertando; si hay huecos, revisar cron-job.org.

**Limitaciones conocidas**:

- Los medios mexicanos grandes bloquean la descarga directa: entran por espejo de
  Google News, con una resolución de enlace extra por nota.
- El cron de GitHub es "mejor esfuerzo": por eso el disparador externo.
- Las fotos son de los medios. Al publicar hay que citar la fuente (el video ya lo
  hace en pantalla) y revisar sus condiciones antes de monetizar.
- La voz clonada exige declarar contenido sintético cuando YouTube lo pida.
