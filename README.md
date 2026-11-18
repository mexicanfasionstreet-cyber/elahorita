# El Ahorita

Canal de noticias en YouTube Shorts, **México primero y el mundo como apoyo**. El
robot busca las noticias más relevantes del día, te las propone por Telegram, monta
un video vertical de 60-70 s con **1 o 2 notas desarrolladas** —no titulares sueltos—
y lo sube al canal.

Marca: **El Ahorita** · `@ElAhorita` · *Ahorita sí es ahorita.*
Promesa: lo más importante de México y el mundo, en menos de un minuto.

---

## Cómo funciona

```
42 fuentes (directas + espejos de Google News)
        │
        ├─ agrupa la misma historia de varios medios  →  cobertura
        ├─ puntúa: cobertura × peso × recencia × pico de entidad × sección
        └─ elige sin repetir personaje (diversidad)
                    │
      ┌─────────────┴──────────────┐
      │                            │
  4 veces al día               tú escribes
  te manda 3 candidatas        /nota <tema o enlace>
      │                            │
   tocas un botón ────────────────┘
                    │
        guion con IA + verificador de datos
                    │
        voz (Voicebox / edge-tts)
                    │
   video 1080×1920: marca, titular, subtítulos karaoke, cierre
                    │
        sube a YouTube + te manda el enlace al chat
```

### Las cuatro franjas

| Hora (Tijuana) | Trabajo |
|---|---|
| 05:00 | Lo que pasó de noche y la agenda del día |
| 12:00 | La nota grande de la mañana |
| 15:00 | Actualización: qué cambió desde el mediodía |
| 20:00 | Cierre: la historia del día completa |

### La mesa de edición

Telegram es el control remoto. Solo atiende tu chat.

- **Candidatas**: llegan 3 historias con botones *Publicar 1/2/3* y *Ninguna hoy*.
- **Aprobación automática**: si una nota gana por goleada, se publica sola; si hay
  empate o tema sensible, te pregunta.
- **`/nota <tema>`**: pides una historia concreta; busca, investiga y la monta.
- **`/nota <enlace>`**: va directo al artículo, sin búsqueda.

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

1. Confirmar que Voicebox suena en el runer (Tailscale + Carla-News).
2. Pasar `YT_PRIVACIDAD` a `public` cuando los videos estén aprobados.
3. Valorar pedir ampliación de cuota a Google si el canal crece a más de 6 clips/día.
4. Vigilar que el cron siga despertando; si hay huecos, revisar cron-job.org.

**Limitaciones conocidas**:

- Los medios mexicanos grandes bloquean la descarga directa: entran por espejo de
  Google News, con una resolución de enlace extra por nota.
- El cron de GitHub es "mejor esfuerzo": por eso el disparador externo.
- Las fotos son de los medios. Al publicar hay que citar la fuente (el video ya lo
  hace en pantalla) y revisar sus condiciones antes de monetizar.
- La voz clonada exige declarar contenido sintético cuando YouTube lo pida.
