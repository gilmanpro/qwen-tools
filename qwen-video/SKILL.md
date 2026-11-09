---
name: qwen-video
description: >
  Genera video con QwenCloud (REST asincrona submit+poll, key sk-sp- del Token Plan resuelta
  sola, misma base y flujo para ambos modelos): HappyHorse 1.1 t2v/i2v/r2v (3-15 s, 480P-1080P,
  audio automatico) y wan3.0-video All-in-One (2-30 s o -1 smart, hasta 30 fps con audio nativo,
  ratio "adaptive", referencias omni-modales: imagenes/video/audio/archivos/links, edicion y
  extension de video; EN la allowlist Token Plan — verificado 2026-11-09, hallazgo R0). Usa
  SIEMPRE que el usuario pida generar video, teaser, animar una imagen o crear un clip con IA
  de Qwen, aunque no nombre la herramienta. El script generar_video.py infiere t2v/i2v/r2v,
  acepta --model wan3.0-video, hace poll cada 15 s y descarga el MP4 (URL expira 24 h); facturacion
  por segundo de salida (~$0.07/s happyhorse; wan3.0 ref $0.035-0.14/s segun resolucion). NO para:
  generar/editar una IMAGEN estatica → skill qwen-imagen; editar video local (recortes, filtros)
  → skill graphic-video (FFmpeg); buscar clips de la web → navegador/webfetch.
license: MIT
metadata:
  version: "3.0"
  split-de: "qwen-tools v2.0"
  api_base_rest: "https://token-plan.maas.qwencloudapi.com/api/v1"
---

# QWEN-VIDEO — HappyHorse 1.1 y wan3.0-video (asincrono submit → poll → descarga)

REST **asincrona** (igual para los dos modelos): `POST {base}/services/aigc/video-generation/video-synthesis`
con header `X-DashScope-Async: enable` → `output.task_id` → poll `GET {base}/tasks/{task_id}` cada
15 s (cadencia x1.5 hasta max 60 s, timeout total 900 s; `--timeout`) y **descarga el MP4
automaticamente** al `--output` (obligatorio — la URL `output.video_url` expira en 24 h). Un
submit sin el header async se rechaza ("current user api does not support synchronous calls").

```
py "%USERPROFILE%\.config\opencode\skills\qwen-video\scripts\generar_video.py" --prompt-file prompt.txt --output video.mp4 --resolution 480P --duration 3
py ...generar_video.py --prompt-file prompt.txt --image foto.png --output video.mp4
py ...generar_video.py --prompt-file prompt.txt --refs a.png,b.png --output video.mp4 --ratio 16:9
py ...generar_video.py --prompt-file prompt.txt --output clip.mp4 --model wan3.0-video --ratio adaptive --duration 20
```

El script SOLO stdlib; `--prompt`/`--prompt-file`, `--image`/`--refs` (los convierte a data URI
base64 si son rutas locales, <=20 MB), `--model` (default: **infiere** — con `--image` i2v, con
`--refs` r2v, si no t2v), `--resolution`, `--ratio`, `--duration`, `--watermark`, `--seed`,
`--base-url`, `--timeout`, `--poll-interval`. Auto-seleccion sin preguntar (como imagen): pista
de ahorro → 480P + 3 s; "guion largo / referencias / editar un video" → wan3.0. **Reportar SIEMPRE**
modelo usado y por que (1 linea).

## MODELOS EN TOKEN PLAN (allowlist exact-string)

`happyhorse-1.1-t2v` / `-i2v` / `-r2v` y **`wan3.0-video`** — este ultimo **ESTA en Token Plan**
(Personal y Team). La doc vieja del monolito decia "wan3.0-video = SOLO pay-as-you-go": FALSO,
corregido con el hallazgo R0 (`.tmp\qwen-split\hallazgo-wan3-video.md`, 2026-11-09, fuentes
`docs.qwencloud.com/token-plan/personal/token-plan-personal-overview#supported-models` y
`/token-plan/best-practices/video-generation#supported-models`). `wan3.0-video-prime` (version
rapida del mismo all-in-one) **NO esta** en Token Plan: allowlist exact-string → fuera. Pedir
cualquier otro nombre → `Model not exist`.

## HAPPYHORSE 1.1 (3-15 s)

MP4 H.264 **24 fps**, 3-15 s, con **audio generado automaticamente** (no desactivable).
Facturacion **por segundo de salida** (`usage.output_video_duration`; $0.07/s 480P, $0.14/s 720P,
$0.18/s 1080P ref PAYG — TP se liquida en Credits; fallidas NO se facturan).

| Parametro | Valores | Notas |
|---|---|---|
| `--resolution` | 480P / 720P / 1080P | La API default es 1080P; **el SCRIPT usa 720P por costo**. Pista de ahorro → 480P + duration 3 |
| `--ratio` | 16:9 default, 9:16, 1:1, 4:3, 3:4, 4:5, 5:4, 9:21, 21:9 | Solo t2v/r2v; i2v hereda el de la imagen. **`adaptive` NO existe en HappyHorse** |
| `--duration` | entero **3-15** s | Default 5; cobrar por segundo → primera prueba SIEMPRE 3 s + 480P |
| `--watermark` | bool | La API default es TRUE → el script envia SIEMPRE `watermark:false` explicito salvo `--watermark` |
| `--seed` | 0-2147483647 | Reproducibilidad aproximada |

**NO enviar `prompt_extend` ni `negative_prompt`**: HappyHorse no los soporta → HTTP 400
`InvalidParameter`. i2v: imagen lados >=300 px, ratio 1:2.5–2.5:1, <=20 MB, JPEG/PNG/WEBP,
exactamente 1. r2v: lado mas corto >=400 px recomendado, <=20 MB, 1-9 referencias. Prompt (en
ingles): sujeto + accion + movimiento de camara + iluminacion + estilo; un solo plano con
movimiento continuo (cortes no funcionan; util: static shot, slow pan, dolly in/out, tracking,
aerial drift, orbit; estilo: cinematic lighting, golden hour, photorealistic, anime, film grain);
en r2v citar `[Image N]` en orden. Generacion tipica ~80-104 s para 5 s/720P; r2v ~40 s; picos
de demanda = cola PENDING.

## WAN3.0-VIDEO — All-in-One (2-30 s; EN Token Plan)

Un solo nombre cubre todos los modos (el modelo enruta segun `input.media[].type` + intent del
prompt): texto→video, **primera frame**, **primera+ultima frame**, referencias omni-modales,
**documento/web→video**, **edicion de video** y **extension de video**. MP4 H.264 **30 fps** con
audio nativo (voz+BGM+efectos; se desactiva con `audio:false` en el body — el script no expone
ese flag, usar curl/reference). Videos de **hasta 30 s** (el doble que HappyHorse) y `duration:-1`
= duracion smart (default 5 s). Prompt hasta 20.000 caracteres (auto-truncado).

| Parametro | Valores | Notas |
|---|---|---|
| `--resolution` | 480P / 720P / 1080P | Default de la API: 1080P (el script mantiene 720P por costo) |
| `--ratio` | **`adaptive` (default API)**, 21:9, 16:9, 4:3, 1:1, 3:4, 9:16 | `adaptive` = elige el ratio segun materiales/intent; **SOLO existe en wan3.0** (HappyHorse lo rechaza). NO tiene 4:5/5:4/9:21 |
| `--duration` | entero **2-30** o **-1** (smart) | Con video de entrada: input + output <=30 s. Edicion/extension: -1 recomendado |
| `--refs` (type `reference_image`) | hasta **10** imagenes, cada <=20 MB | En el prompt citar `Image 1`, `Video 1`, `Audio 1` (cada tipo cuenta su propio indice) |
| `watermark` / `seed` | **no documentados publicamente para wan3.0** | El script NO los envia por defecto con wan3.0; omitir `watermark` **CONFIRMADO EN VIVO 2026-11-09** (sin HTTP 400); `--watermark`/`--seed` explicitos siguen sin evidencia → verificar antes de usar |

**CONFIRMADO EN VIVO 2026-11-09 con `sk-sp-`** (evidencia `.tmp\qwen-split\tests\qwen-video\generar_video_wan30.json` + `wan30.mp4`, 5.142.693 B ≈ 5.1 MB; tarea `48100e29-476c-4b17-8d02-ac9b9a51eb9a`): submit async OK por la base TP documentada; `duration:-1` (smart) → **5.0 s reales**; `ratio:"adaptive"` → resuelto a **16:9**; salida **30 fps**; `watermark` omitido en el body → **sin HTTP 400**.

Medios `input.media[]` (detalle literal + bodies de ejemplo en `references\api-happyhorse-video.md`
§5-§7): `first_frame` (max 1) / `last_frame` (max 1) — **excluyentes** con el resto;
`reference_image` (max 10), `reference_video` (max 5, total <=15 s, cada archivo <=100 MB,
>=16 fps), `reference_audio` (max 5, total <=15 s, cada <=15 MB, wav/mp3), `file` (max 1: docx,
doc, xlsx, xls, pptx, ppt, pdf, txt, md — URL publica), `link` (max 1: web publica sin login;
excluyente con `file`). Edicion/extension = `reference_video` (+ imagenes/audio opcionales) +
prompt con intención explicita ("edit video", "remove", "replace", "extend", "continue"). El
script hoy expone `--image` (→ `first_frame`) y `--refs` (→ `reference_image`); los demas types
(`last_frame`, video/audio/file/link) → curl con el body literal de la reference (F2 puede
ampliar el script si hace falta — no inventar flags sin verificar). Reglas de referencias reales
y moderacion igual que imagen: marcas registradas y personas reales pueden disparar rechazos.

**Costos:** ref pay-as-you-go **por segundo de salida** — wan3.0: $0.035/s 480P, $0.07/s 720P,
$0.14/s 1080P (con 30% desc. de lista al 2026-11-09); happyhorse: $0.07/s 480P, $0.14/s 720P,
$0.18/s 1080P. **Con Token Plan (`sk-sp-*`) la liquidacion es en Credits**, los USD son solo
referencia de costo relativo. Rate limits wan3.0: 5 tareas concurrentes / cola async 500 /
RPM 300. Fallidas NO se facturan.

## KEY Y BASES — resolucion automatica (familia B, TP primero)

**Nunca imprimir la key ni el body** (stdout, stderr ni `--out`). Sin ninguna key → exit 2 con
instruccion (crear key en https://home.qwencloud.com/api-keys). Precedencia: 1.
`DASHSCOPE_API_KEY`, 2. `ANTHROPIC_AUTH_TOKEN`, 3. `~/.local/share/opencode/auth.json`
(`alibaba-token-plan` / `alibaba-token-plan-cn`). Host por prefijo (o `--base-url` que manda):

| Key | Base REST (submit + poll) |
|---|---|
| `sk-sp-*` (Token Plan) | `https://token-plan.maas.qwencloudapi.com/api/v1` — **las bases Token Plan NO llevan region ID** (TP solo en Singapur) |
| `sk-*` / `sk-ws-*` (pay-as-you-go) | `https://ap-southeast-1.maas.qwencloudapi.com/api/v1` — forma con region ID segun doc regions; la pelada `maas.qwencloudapi.com` es el alias Singapur |

Key `sk-sp-*` = uso INTERACTIVO (generar clips a demanda: normal; automatizacion por lotes /
batch: prohibida por terminos → usar pay-as-you-go). Los USD de las tablas son referencia
(verificados 2026-10-02 y marketplace 2026-11-09, pueden cambiar).

## ERRORES (dominio video)

| Situacion | Accion |
|---|---|
| HTTP 429 / `Throttling*` en submit | el script reintenta 2x (10/20 s); persiste = reducir ritmo (TP: esperar 1 min) |
| HTTP 401 / `InvalidApiKey` | key invalida o key↔host incorrectos (`sk-sp-*` ⇒ `token-plan.maas.qwencloudapi.com`). Detenerse |
| `Model not exist` | fuera de allowlist TP (validos: happyhorse-1.1-t2v/-i2v/-r2v, **wan3.0-video**; `wan3.0-video-prime` NO esta en TP) |
| `DataInspectionFailed` | moderacion — puede aparecer **en el submit (HTTP 400) O en el poll (FAILED)** → reescribir prompt / cambiar imagen |
| HTTP 400 `InvalidParameter` | happyhorse: duration 3-15, ratio valido, refs 1-9, i2v 1 imagen, NO `prompt_extend`/`negative_prompt`; wan3.0: duration 2-30/-1, ratio sin 4:5/5:4/9:21, refs 1-10 |
| `FAILED` + `output.code`/`message` (poll) | leer el codigo dentro de `output` (HTTP es 200): moderacion/parametros |
| `UNKNOWN` (poll) | tarea expirada (la informacion se conserva 24 h) → regenerar desde el principio |
| `CANCELED` | cancelada (solo tareas PENDING se pueden cancelar: `POST {base}/tasks/{id}/cancel`) |
| Poll con 429/5xx/red | transitorio: el script reintenta, NO aborta |
| `Arrearage` | saldo pendiente (pay-as-you-go): regularizar pago |
| SUCCEEDED sin `video_url` / descarga falla | la URL expira en 24 h → regenerar |

**Exit codes**: `0` OK · `1` error de API/generacion/descarga · `2` configuracion/uso (falta
key/prompt, rango invalido, combinar --image con --refs, modelo/ratio incompatibles). Sin exit 3:
video NO consume el presupuesto diario de busqueda. Cadencia de consulta: 20 QPS max en
`GET /tasks/...` — el script usa 15-60 s, no hacer poll agresivo.

## ARCHIVOS

```
qwen-video/
├── SKILL.md
├── README.md
├── scripts/generar_video.py           # submit async + reintentos 429 + poll x1.5 + descarga MP4 (happyhorse y wan3.0)
└── references/api-happyhorse-video.md # bodies literales ambos modelos, media types wan3.0, estados, billing, errores
```

Referencias a un solo nivel: leer la reference SOLO cuando el body de esta skill no baste.
