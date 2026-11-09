# API HappyHorse Video y wan3.0-video (QwenCloud) — referencia completa

Flujo **asincrono** obligatorio (IDENTICO para los dos modelos): `POST submit` → `GET poll` →
descargar `video_url` (expira en 24 h).
Base URL: Token Plan (`sk-sp-*`) `https://token-plan.maas.qwencloudapi.com/api/v1` (**las bases
TP no llevan region ID**) · pay-as-you-go `https://ap-southeast-1.maas.qwencloudapi.com/api/v1`
(forma con region ID segun doc regions; la pelada `maas.qwencloudapi.com` = alias Singapur).

## Fuentes oficiales

- https://docs.qwencloud.com/api-reference/video-generation/happyhorse-text-to-video/create-task
- https://docs.qwencloud.com/api-reference/video-generation/happyhorse-text-to-video/query-result
- https://docs.qwencloud.com/api-reference/video-generation/happyhorse-image-to-video/create-task
- https://docs.qwencloud.com/api-reference/video-generation/happyhorse-image-to-video/query-result
- https://docs.qwencloud.com/api-reference/video-generation/happyhorse-reference-to-video/create-task
- https://docs.qwencloud.com/api-reference/video-generation/happyhorse-reference-to-video/query-result
- https://docs.qwencloud.com/api-reference/video-generation/wan30-video/create-task **(wan3.0, leida en vivo 2026-11-09)**
- https://docs.qwencloud.com/api-reference/video-generation/wan30-video/query-result
- https://docs.qwencloud.com/developer-guides/video-generation/wan30-video (bodies literales, media types, FAQ)
- https://docs.qwencloud.com/developer-guides/getting-started/video-models
- https://docs.qwencloud.com/token-plan/best-practices/integrate-multimodal-gen y
  https://docs.qwencloud.com/token-plan/best-practices/video-generation#supported-models
- https://docs.qwencloud.com/token-plan/personal/token-plan-personal-overview#supported-models (allowlist)
- https://www.qwencloud.com/models/wan3.0-video (ficha marketplace: precios PAYG, hasta 30 s)
- https://docs.qwencloud.com/developer-guides/run-and-scale/async-task-management
- https://docs.qwencloud.com/api-reference/preparation/error-messages

## 1. SUBMIT — crear tarea (ambos modelos)

`POST {base}/services/aigc/video-generation/video-synthesis`

Headers:

```
Content-Type: application/json
Authorization: Bearer <API_KEY>
X-DashScope-Async: enable
```

Sin `X-DashScope-Async: enable` la API rechaza ("current user api does not support synchronous
calls"). Modelos HappyHorse: `happyhorse-1.1-t2v`, `happyhorse-1.1-i2v`, `happyhorse-1.1-r2v`.
Modelo wan3.0: `wan3.0-video` (y `wan3.0-video-prime` en pay-as-you-go — **fuera de Token Plan**;
ver §7).

### 1a. t2v (texto → video)

`input.prompt` es un **string llano** (NO el formato `messages` de las imagenes).

```bash
curl -X POST "https://token-plan.maas.qwencloudapi.com/api/v1/services/aigc/video-generation/video-synthesis" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_KEY" \
  -H "X-DashScope-Async: enable" \
  -d '{
    "model": "happyhorse-1.1-t2v",
    "input": { "prompt": "A red panda astronaut floating gently in space, Earth glowing in the background, cinematic lighting, slow smooth camera drift" },
    "parameters": { "resolution": "720P", "ratio": "16:9", "duration": 5, "watermark": false }
  }'
```

### 1b. i2v (imagen → video)

`media` con **exactamente 1** elemento `type:"first_frame"`. `prompt` OPCIONAL (dirige la
animacion). **No enviar `ratio`**: el video hereda el aspect ratio de la imagen.

Restricciones de la imagen: lados ≥300 px, ratio entre 1:2.5 y 2.5:1, ≤20 MB, JPEG/PNG/WEBP.
`url` admite URL publica **o** data URI: `data:image/png;base64,...`.

```json
{
  "model": "happyhorse-1.1-i2v",
  "input": {
    "prompt": "The scene comes alive: soft wind moves the trees, the camera slowly dollies in, golden hour light",
    "media": [ { "type": "first_frame", "url": "https://example.com/foto.png" } ]
  },
  "parameters": { "resolution": "720P", "duration": 5, "watermark": false }
}
```

### 1c. r2v (referencias → video)

`media` con 1-9 elementos `type:"reference_image"`. `prompt` **OBLIGATORIO**, citando `[Image 1]`,
`[Image 2]`... en el mismo orden del array. Aqui `ratio` SI aplica. Lado mas corto ≥400 px
recomendado, ≤20 MB por imagen.

```json
{
  "model": "happyhorse-1.1-r2v",
  "input": {
    "prompt": "The woman from [Image 1] walks through the night market of [Image 2], neon reflections, handheld tracking shot, cinematic",
    "media": [
      { "type": "reference_image", "url": "https://example.com/mujer.png" },
      { "type": "reference_image", "url": "https://example.com/mercado.png" }
    ]
  },
  "parameters": { "resolution": "720P", "ratio": "16:9", "duration": 5, "watermark": false }
}
```

### 1d. Respuesta del submit

```json
{
  "request_id": "7a2c9f0e-....",
  "output": { "task_id": "3f2b8c1a-....", "task_status": "PENDING" }
}
```

### 1e. Parametros HappyHorse (`parameters`)

| Parametro | Tipos/valores | Default | Notas |
|---|---|---|---|
| `resolution` | `480P` `720P` `1080P` | **1080P** en la API (el script generar_video.py usa 720P por costo) | Define la altura del fotograma |
| `ratio` | `16:9` `9:16` `1:1` `4:3` `3:4` `4:5` `5:4` `9:21` `21:9` | `16:9` | Solo t2v/r2v; OMITIR en i2v. **`adaptive` NO existe aqui** (solo wan3.0) |
| `duration` | entero 3-15 (segundos) | 5 | Facturacion por segundo generado |
| `watermark` | bool | **true** en la API | El script envia `false` explicito salvo `--watermark` |
| `seed` | 0-2147483647 | aleatorio | Reproducibilidad aproximada |

**No existen** `prompt_extend` ni `negative_prompt` en HappyHorse: enviarlos produce HTTP 400
`InvalidParameter`. El audio del MP4 se genera automaticamente (no hay parametro documentado para
controlarlo). Formato: MP4 H.264, **24 fps**.

## 2. POLL — consultar tarea

`GET {base}/tasks/{task_id}` con header `Authorization: Bearer <API_KEY>`.

Estados de `output.task_status`: `PENDING` → `RUNNING` → `SUCCEEDED` | `FAILED` (+ `CANCELED`;
`UNKNOWN` = la informacion expiro, solo se conserva 24 h).

Cadencia recomendada (implementada en el script): 15 s inicial, x1.5 en cada ronda hasta max 60 s;
timeout total 900 s. Errores transitorios del poll (429/Throttling, 5xx, red) → reintentar, NO
abortar.

### Respuesta SUCCEEDED (literal, happyhorse t2v 5 s 720P)

```json
{
  "request_id": "7a2c9f0e-....",
  "output": {
    "task_id": "3f2b8c1a-....",
    "task_status": "SUCCEEDED",
    "video_url": "https://dashscope-result.oss-cn-beijing.aliyuncs.com/....mp4?Expires=...",
    "submit_time": "2026-09-28 15:58:12.345",
    "scheduled_time": "2026-09-28 15:58:13.001",
    "end_time": "2026-09-28 16:00:02.567"
  },
  "usage": {
    "duration": 5,
    "output_video_duration": 5,
    "video_count": 1,
    "SR": 720,
    "ratio": "16:9"
  }
}
```

`video_url`: MP4 codificado H.264. **Expira en 24 h** → descargar de inmediato.
`usage.duration` / `output_video_duration` = segundos facturados (facturacion por segundo de
video, modulada por `SR`=resolucion).

### Respuesta FAILED

El `code`/`message` van DENTRO de `output` (no en el HTTP, que es 200):

```json
{
  "output": {
    "task_id": "3f2b8c1a-....",
    "task_status": "FAILED",
    "code": "DataInspectionFailed",
    "message": "Input data may contain inappropriate content."
  }
}
```

Manejar los errores de moderacion/parametros en AMBAS fases: pueden rechazar en el submit (HTTP
400) o despues, en el poll (FAILED).

## 3. Gestion asincrona de tareas

Documentado en https://docs.qwencloud.com/developer-guides/run-and-scale/async-task-management :

- **Listar**: `GET {base}/tasks/?start_time=<ts>&end_time=<ts>&status=<s>&model_name=<m>&page_no=<n>&page_size=<n>` — el rango `start_time`/`end_time` debe ser **≤24 h**; `status` filtra por estado.
- **Cancelar**: `POST {base}/tasks/{task_id}/cancel` — solo tiene efecto mientras la tarea esta en `PENDING` (una vez `RUNNING` no se puede cancelar).
- **Rate limit de consulta (GET /tasks/...)**: **20 QPS** — no hacer poll agresivo; el script usa 15-60 s de cadencia.
- Valididez: `task_id` e informacion de la tarea se conservan 24 h; despues el estado pasa a `UNKNOWN`.

## 4. Errores (submit y plan — ambos modelos)

| Codigo | HTTP | Causa / accion |
|---|---|---|
| `Throttling` / `Throttling.RateQuota` | 429 | Rate limit → esperar 5-15 s y reintentar (max 2) |
| `InvalidApiKey` | 401 | Key invalida, o key `sk-sp-*` enviada al host equivocado (debe ser `token-plan.maas.qwencloudapi.com`) |
| `InvalidParameter` | 400 | Rango invalido (happyhorse: duration 3-15, enums resolution/ratio, refs 1-9, i2v exactamente 1 imagen; wan3.0: duration 2-30 o -1, ratio sin 4:5/5:4/9:21, refs 1-10) o parametro no soportado (happyhorse: `prompt_extend`/`negative_prompt`) |
| `DataInspectionFailed` | 400 o FAILED en poll | Moderacion de contenido → reescribir prompt / cambiar imagen |
| `Model not exist` | 400 | Modelo no disponible en el plan (Token Plan: happyhorse-1.1-t2v/i2v/r2v y **wan3.0-video**; NO `wan3.0-video-prime`) |
| `Arrearage` | 400/403 | Cuenta con saldo pendiente → regularizar pago |
| `IPInfringementSuspect` | 400 o FAILED en poll | Posible infraccion de PI en prompt/imagen → reformular |
| `RequestTimeOut` | — | Timeout interno de la tarea → reintentar la generacion |
| `UNKNOWN` (poll) | 200 | Tarea expirada (>24 h) → regenerar |

Lista completa: https://docs.qwencloud.com/api-reference/preparation/error-messages

## 5. Modelos: HappyHorse vs wan3.0 (CORREGIDO 2026-11-09)

- **HappyHorse 1.1** (`t2v`/`i2v`/`r2v`): los 3 confirmados en Token Plan. Entrada `prompt` como
  string llano; i2v/r2v usan `media[]` con `first_frame`/`reference_image`.
- **wan3.0-video**: **SI esta en la allowlist del Token Plan** (Personal y Team — fila "Wan |
  wan3.0-video | Video generation" en
  https://docs.qwencloud.com/token-plan/personal/token-plan-personal-overview#supported-models y
  "Text, images, or reference materials — All-in-one" en
  https://docs.qwencloud.com/token-plan/best-practices/video-generation#supported-models). La
  version de esta referencia anterior decia "**no estan confirmados en Token Plan**" — FALSO,
  corregido con el hallazgo R0 (`.tmp\qwen-split\hallazgo-wan3-video.md`; el monolito viejo
  tambien afirmaba "SOLO pay-as-you-go" — obsoleto). La allowlist es **exact-string**:
  `wan3.0-video-prime` NO esta en TP (existe solo en pay-as-you-go). La familia `wan2.7-*` de
  video (t2v/i2v separados) no aplica: **wan3.0-video reemplaza a wan2.7-t2v/wan2.7-i2v** con un
  unico nombre (FAQ oficial). Detalle completo en §6-§7.

## 6. WAN3.0-VIDEO — All-in-One (mismo endpoint async que HappyHorse)

Fuentes: create-task/query-result §"Fuentes" + developer guide
https://docs.qwencloud.com/developer-guides/video-generation/wan30-video (bodies copiados
literalmente el 2026-11-09). Un solo modelo cubre TODOS los modos; el modelo enruta segun el
campo `type` de `input.media[]` y la intencion del prompt — **sin cambiar el nombre del modelo**:

| Task type | Trigger | Notas |
|---|---|---|
| Text-to-video | solo `prompt`, sin `media` | resolution/ratio/duration libres; narrativa multi-shot hasta 30 s con dialogos+BGM automaticos |
| First frame to video | `media[].type = first_frame` (max 1) | `ratio: "adaptive"` recomendado (auto-matching del aspect de la imagen) |
| First+last frame | `first_frame` + `last_frame` (1 c/u) | genera la transicion |
| Image reference | `reference_image` (max **10**, c/u ≤20 MB) | personajes/objetos/estilo consistentes |
| Video reference | `reference_video` (max 5, total ≤15 s, archivo ≤100 MB, ≥16 fps) | replica camara/accion |
| Audio reference | `reference_audio` (max 5, total ≤15 s, c/u ≤15 MB, wav/mp3) | lip-sync/danza al ritmo |
| Combined reference | cualquier mezcla de image+video+audio | el prompt cita `Image 1`, `Video 1`, `Audio 1` — **cada tipo cuenta su propio indice** |
| File/Web → video | `file` (max 1: docx, doc, xlsx, xls, pptx, ppt, pdf, txt, md) o `link` (max 1, pagina publica sin login), combinables con references | parsea el documento/web y genera video |
| Video editing | `reference_video` (+ refs) + prompt con intencion ("edit video", "remove", "replace", "change to") | `ratio: adaptive`, `duration: -1` recomendados |
| Video extension | `reference_video` (+ refs) + prompt ("extend", "continue", "extend forward/backward") | forward/backward/both; input+output ≤30 s |

`reference_xx`/`file`/`link` y `first_frame`/`last_frame` son **mutuamente excluyentes** en la
misma request. `prompt` hasta **20.000 caracteres** (auto-truncado; "either `prompt` or `media`
is required"). `media[].url` admite URL publica o data URI base64 (`data:{MIME};base64,{data}`).

### Body literal t2v largo (doc developer guide, "Text-to-video" Quick Start)

```bash
curl --location '{base}/services/aigc/video-generation/video-synthesis' \
    -H 'X-DashScope-Async: enable' \
    -H "Authorization: Bearer $API_KEY" \
    -H 'Content-Type: application/json' \
    -d '{
    "model": "wan3.0-video",
    "input": {
        "prompt": "A 20-second ultra-widescreen plush universe adventure clip, featuring ultra-fine plush textures throughout, cinematic space scale ... [prompt completo en la doc]"
    },
    "parameters": {
        "resolution": "480P",
        "ratio": "adaptive",
        "duration": 20,
        "prompt_extend": true
    }
}'
```

### Body literal first_frame (doc, "Image-to-video")

```json
{
  "model": "wan3.0-video",
  "input": {
    "prompt": "A cat running on the grass",
    "media": [ { "type": "first_frame", "url": "https://cdn.translate.alibaba.com/r/wanx-demo-1.png" } ]
  },
  "parameters": { "resolution": "720P", "ratio": "adaptive", "duration": 5 }
}
```

### Body literal file→video (doc, create-task ejemplo "File to video")

```json
{
  "model": "wan3.0-video",
  "input": {
    "prompt": "A premium smart glasses product ad with a minimalist, futuristic, and fashionably sophisticated style. ... [prompt descriptivo largo; el documento glass.pptx aporta los datos]",
    "media": [ { "type": "file", "url": "https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20260806/ebapmr/glass.pptx" } ]
  },
  "parameters": { "resolution": "480P", "ratio": "adaptive", "duration": 10, "prompt_extend": true }
}
```

### Body literal referencia combinada (doc, "Multi-modal reference")

```json
{
  "model": "wan3.0-video",
  "input": {
    "prompt": "Video 1 holds Image 3, sitting on the chair in Image 4, playing a soothing country folk song, and says: \"The sunshine is so nice today.\" Image 1 holds Image 2 in hand, walks past Video 1, places Image 2 on the table next to Video 1, and says: \"That sounds great, can you sing it again?\"",
    "media": [
      { "type": "reference_image", "url": "https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20260408/sjuytr/wan-r2v-object-girl.jpg" },
      { "type": "reference_video", "url": "https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20260129/qigswt/wan-r2v-role2.mp4" },
      { "type": "reference_image", "url": "https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20260129/rtjeqf/wan-r2v-object3.png" },
      { "type": "reference_image", "url": "https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20260129/qpzxps/wan-r2v-object4.png" },
      { "type": "reference_image", "url": "https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20260129/wfjikw/wan-r2v-backgroud5.png" }
    ]
  },
  "parameters": { "resolution": "720P", "ratio": "adaptive", "duration": 5, "prompt_extend": true }
}
```

### Body literal video-editing y extension (doc)

```json
{ "model": "wan3.0-video",
  "input": { "prompt": "Convert the entire scene to clay style",
    "media": [ { "type": "reference_video", "url": "https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20260402/ldnfdf/wan2.7-videoedit-style-change.mp4" } ] },
  "parameters": { "resolution": "720P", "prompt_extend": true } }
```

```json
{ "model": "wan3.0-video",
  "input": { "prompt": "Extend Video 1 backward, the baker brings up the brushed bread, puts the brush aside, the camera follows the baker to the oven behind for baking",
    "media": [ { "type": "reference_video", "url": "https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20260414/rptnhd/wan2.7-i2v-video-continuation-2.mp4" } ] },
  "parameters": { "resolution": "720P", "ratio": "adaptive", "prompt_extend": true } }
```

## 7. Parametros wan3.0-video (`parameters`) — tabla oficial create-task

| Parametro | Tipos/valores | Default | Notas |
|---|---|---|---|
| `resolution` | `480P` `720P` `1080P` | **1080P** | Como HappyHorse; el script mantiene 720P por costo |
| `ratio` | **`adaptive`**, `21:9`, `16:9`, `4:3`, `1:1`, `3:4`, `9:16` | **`adaptive`** (elige segun materiales/intent) | **`adaptive` SOLO existe en wan3.0** (la doc lo lista como default suyo y NO aparece en HappyHorse). Wan3.0 NO tiene `4:5`, `5:4`, `9:21` |
| `duration` | entero **2-30** o **`-1`** (duracion smart: el modelo recomienda; equivale a default 5 s) | 5 | Sin video de entrada: 2-30. Con video de entrada: input+output **≤30 s**. En edicion/extension se recomienda `-1` (conserva ratio y duracion originales). **La doc anterior de la skill decia 3-30: la cifra oficial es 2-30** — el script valida 2-30/-1 para wan3.0 |
| `audio` | bool | **true** (audio-video nativo: voz+BGM+efectos) | Se DESACTIVA con `audio:false` — parametro exclusivo de wan3.0 (HappyHorse no expone control) |
| `prompt_extend` | bool | — | La doc lo usa (`true`) en SUS ejemplos de wan3.0. El script NO lo envia (default del servidor): **no probado 2026-11-09**; HappyHorse rechaza `prompt_extend` (HTTP 400) → para wan3.0 NO enviarlo por defecto hasta verificar |
| `watermark` | — | — | **NO figura en la doc publica de wan3.0** → el script solo lo manda si `--watermark` explicito. **CONFIRMADO EN VIVO 2026-11-09 (sk-sp-)**: omitirlo no da error (sin HTTP 400); `--watermark` explicito sigue sin probar |
| `seed` | — | — | **NO documentado para wan3.0** en create-task → **no probado 2026-11-09**; si se pasa `--seed` con wan3.0 puede HTTP 400 → no usarlo hasta verificar |

Salida: **MP4 H.264, 30 fps** (HappyHorse: 24 fps), URL valida 24 h.

### Respuesta SUCCEEDED wan3.0 (literal, query-result oficial)

```json
{
  "request_id": "78c9b768-0285-996c-b682-xxxxxx",
  "output": {
    "task_id": "17ed7e50-00cf-4509-aea1-xxxxxx",
    "task_status": "SUCCEEDED",
    "submit_time": "2026-08-06 10:01:35.452",
    "scheduled_time": "2026-08-06 10:01:35.507",
    "end_time": "2026-08-06 10:13:33.838",
    "orig_prompt": "A golden retriever running on a sunny beach, waves crashing in the background, cinematic lighting",
    "video_url": "https://dashscope-result-sg.oss-ap-southeast-1.aliyuncs.com/xxx/video.mp4"
  },
  "usage": {
    "video_count": 1,
    "duration": 5,
    "input_video_duration": 0,
    "output_video_duration": 5,
    "fps": 30,
    "SR": 720,
    "ratio": "16:9"
  }
}
```

Facturacion **por segundo de salida** (`usage.output_video_duration`, modulada por `SR`); con
video de entrada `input_video_duration` refleja lo consumido. Estados del poll, cancelacion y
cadencia: identicos a §2-§3.

### Precios y limites wan3.0-video

- **Pay-as-you-go (lista, marketplace 2026-11-09, con 30% de desc. promocional):** $0.035/s
  480P · $0.07/s 720P · $0.14/s 1080P. **Con Token Plan (`sk-sp-*`) la liquidacion es en
  Credits** — los USD son solo referencia de costo relativo (las tablas pueden cambiar).
- Rate limits (ficha marketplace): **5 tareas concurrentes · cola async 500 · 300 RPM**.
- Las tareas tardan minutos (el ejemplo de la doc: submit 10:01 → end 10:13 para un video):
  mantener el timeout del script (900 s) alto o subir `--timeout`.
- Nota terminos TP: uso interactivo; `wan3.0-video-prime` (la variante rapida del enum de la doc
  — mismo endpoint, misma firma) **NO esta en la allowlist TP** → solo con key pay-as-you-go.
- Lo que la doc de parámetros NO aclara para wan3.0: **CONFIRMADO EN VIVO 2026-11-09 con
  `sk-sp-`** (evidencia `.tmp\qwen-split\tests\qwen-video\generar_video_wan30.json` + `wan30.mp4`,
  5.142.693 B): submit async OK, `duration:-1` (smart) → **5.0 s reales**, `ratio:"adaptive"` →
  resuelto **16:9**, salida **30 fps**, `watermark` omitido en el body → **sin HTTP 400**. Quedan
  **no probados** `prompt_extend` y `seed` → no enviarlos por defecto hasta verificar.

## 8. Prompt tips (wan3.0, doc)

La plataforma publica una skill de optimizacion de prompts Wan 3.0 (`/wan3-pe`) — descarga
`wan3-pe.zip` enlazada en https://docs.qwencloud.com/developer-guides/video-generation/wan30-video
#prompt-tips. Para HappyHorse sigue valiendo la guia de la SKILL.md (un plano, movimiento
continuo, terminos de camara en ingles).

## 9. Script de referencia

`scripts/generar_video.py` (solo stdlib) implementa submit + reintentos 429 + poll con cadencia
x1.5 + descarga inmediata + validaciones previas (duration **3-15 happyhorse / 2-30 o -1
wan3.0**, enums resolution/ratio por modelo — `adaptive` solo wan3.0 —, refs 1-9 happyhorse /
1-10 wan3.0, imagen unica i2v, ≤20 MB, data URI base64 para rutas locales) y printea JSON final
`{ok, request_id, task_id, model, base, video, segundos, usage}`. `--model wan3.0-video` fuerza
el all-in-one; los modos finos de wan3.0 (last_frame, reference_video/audio, file, link, audio,
prompt_extend) se operan por curl con los bodies de §6 hasta su verificacion (watermark omitido
ya confirmado 2026-11-09; `prompt_extend`/`seed` aun no probados — ver §7).
