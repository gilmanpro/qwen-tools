# API Qwen-Image (QwenCloud) — Referencia

Fuentes: https://docs.qwencloud.com/developer-guides/image-generation/text-to-image ·
https://docs.qwencloud.com/api-reference/image-generation/qwen-text-to-image ·
https://docs.qwencloud.com/developer-guides/image-generation/image-editing (edit: body literal
abajo, verificado en vivo 2026-11-09)

## Bases URL (autenticacion)

| Tipo de key | Base |
|---|---|
| Token Plan (`sk-sp-*`) | `https://token-plan.maas.qwencloudapi.com/api/v1` — **las bases TP NO llevan region ID** (Token Plan solo en Singapur) |
| Pay-as-you-go (`sk-*`, `sk-ws-*`) | `https://ap-southeast-1.maas.qwencloudapi.com/api/v1` (Singapur, forma con region ID segun https://docs.qwencloud.com/developer-guides/getting-started/regions — la forma pelada `maas.qwencloudapi.com` es su alias equivalente y codigo viejo sigue funcionando) |

Doc Token Plan multimodal: https://docs.qwencloud.com/token-plan/best-practices/integrate-multimodal-gen
Modelos de imagen en la allowlist Token Plan (exact-string): `qwen-image-3.0-pro`, `wan2.7-image`,
`wan2.7-image-pro`. (Video async → skill `qwen-video`; voz → skill `qwen-audio`.)

## Endpoint sincrono (Qwen-Image, todas las series)

```
POST {base}/services/aigc/multimodal-generation/generation
Headers:
  Content-Type: application/json
  Authorization: Bearer <key>
```

Body (single-turn: exactamente 1 mensaje `user` con exactamente 1 objeto `text`):

```json
{
  "model": "qwen-image-3.0-pro",
  "input": {
    "messages": [
      { "role": "user", "content": [ { "text": "<prompt>" } ] }
    ]
  },
  "parameters": {
    "negative_prompt": "",
    "prompt_extend": true,
    "prompt_extend_mode": "direct",
    "enable_thinking": true,
    "watermark": false,
    "size": "2048*2048",
    "n": 1,
    "seed": 42
  }
}
```

Respuesta 200:

```json
{
  "output": {
    "choices": [
      { "finish_reason": "stop",
        "message": { "role": "assistant", "content": [ { "image": "https://dashscope-result-sh.oss-cn-shanghai.aliyuncs.com/xxx.png?Expires=xxx" } ] } }
    ]
  },
  "usage": { "output_width": 2048, "output_height": 2048, "input_image_count": 0,
             "input_image_type": "qima_input_2k", "output_image_count": 1, "output_image_type": "qima_output_2k" },
  "request_id": "d0250a3d-..."
}
```

- `output.choices[].message.content[].image` → URL del PNG, **valida 24 h** (descargar ya). Un choice por imagen generada.
- Billing 3.0: por imagen de salida; tier `*_1k` si area ≤ 2,250,000 px, si no `*_2k`. Las
  fallidas NO se facturan.

## Modelos aceptados (campo `model`, enum oficial)

`qwen-image-3.0-pro`, `qwen-image-3.0`, `qwen-image-2.0-pro` (+ snapshots `-2026-06-22`,
`-2026-04-22`, `-2026-03-03`), `qwen-image-2.0` (+ `-2026-03-03`), `qwen-image-max`
(+ `-2025-12-30`), `qwen-image-plus` (+ `-2026-01-09`), `qwen-image`. **En Token Plan solo los 3
de la tabla de arriba** (el resto es pay-as-you-go / otros planes).

## Parametros (detalle oficial)

| Parametro | Tipo / default | Notas |
|---|---|---|
| `negative_prompt` | string ≤500, "" | Se trunca el exceso. NO soportado por wan2.7-image(-pro) ni por qwen-image-2.1 |
| `size` | "2048*2048" | 3.0: 512\*512–2048\*2048, ratio 1:8–8:1; omitir → auto segun prompt. 2.0: mismo rango, default = el de la imagen de entrada en edicion. **wan2.7-image: area 589824–16777216 px** (`512*512` → HTTP 400 literal `Total pixels (262144) must be between 589824 and 16777216`; minimo practico `768*768`; F2c 2026-11-09). wan2.7-image-pro: mismo rango que wan2.7-image salvo verificacion. max: custom o fijos. plus/image: solo fijos |
| `n` | int 1, rango 1–6 | 3.0/2.0: 1-6. max/plus: fijo 1 |
| `prompt_extend` | bool true | Reescritura del prompt (+3-4 s). false → prompt literal |
| `prompt_extend_mode` | "direct" \| "agent" | Solo serie 3.0; `agent` = reescritura fina, SOLO text-to-image (en edicion → 400) |
| `enable_thinking` | bool true | Solo serie 3.0 (T2I y edicion directa; no en agent-editing); requiere prompt_extend=true; +calidad +tiempo |
| `watermark` | bool false | Marca "Qwen-Image" esquina inferior derecha |
| `seed` | int 0–2147483647 | Igual seed ≈ resultados consistentes (no identicos) |

Tamanos fijos qwen-image-max/plus/image: `1664*928` (16:9, default), `1472*1104` (4:3),
`1328*1328` (1:1), `1104*1472` (3:4), `928*1664` (9:16).

Limites de prompt: serie 3.0 → 4500 tokens (recomendado); serie 2.0 → 1300; resto → 800. Exceso truncado.

## EDICION (qwen-image-3.0-pro / serie 3.0-2.0) — body LITERAL de la doc oficial

Source: https://docs.qwencloud.com/developer-guides/image-generation/image-editing (fetch
2026-11-09). Mismo endpoint sync `{base}/services/aigc/multimodal-generation/generation`; el
`content` del unico mensaje `user` lleva las imagenes (1-3; wan2.7: hasta 9) Y luego el texto con
la instruccion — el orden del array define "Image 1", "Image 2"...:

```json
{
  "model": "qwen-image-3.0-pro",
  "input": {
    "messages": [
      { "role": "user", "content": [
        { "image": "https://.../input1.png" },
        { "image": "https://.../input2.png" },
        { "image": "https://.../input3.png" },
        { "text": "The girl in Image 1 wears the black dress from Image 2 and sits in the pose from Image 3." }
      ] }
    ]
  },
  "parameters": { "n": 2, "watermark": false, "negative_prompt": " ", "prompt_extend": true, "size": "1024*1536" }
}
```

Equivalentes curl/SDK — la doc trae el SDK Python (`MultiModalConversation.call(model="qwen-image-3.0-pro", messages=..., n=2, watermark=False, negative_prompt=" ", prompt_extend=True, size="1024*1536")`).

Restricciones de las imagenes de entrada: JPG/JPEG/PNG/BMP/TIFF/WEBP/GIF (animado: solo primera
frame); lados 1-8000 px (recomendado 384-2048); ratio lado mayor:menor <=10:1; <=10 MB por
imagen; URL publica o base64 data URI `data:<mime>;base64,...`. Salida: PNG. En edicion:
`prompt_extend_mode` SOLO `direct` (`agent` → 400); `enable_thinking` valido en edicion directa
(serie 3.0). La serie `qwen-image-2.1-pro/turbo` admite 1-10 imagenes (fuera de TP).

**Edicion por modo OpenAI-compatible (alterna, pay-as-you-go)**: `POST
{base-reg}/compatible-mode/v1/images/generations` compartiendo el endpoint de t2i — pasar `image`
(string o array de URLs/data URI; 3.0: 1-3) lo convierte en i2i; NO usa multipart `/images/edits`
ni mask:

```bash
curl --location 'https://ap-southeast-1.maas.qwencloudapi.com/compatible-mode/v1/images/generations' \
  --header 'Content-Type: application/json' --header "Authorization: Bearer $API_KEY" \
  --data '{"model":"qwen-image-3.0-pro","prompt":"Change the background to an afternoon cafe, keeping the facial features and hairstyle unchanged","image":"https://example.com/input.png","size":"1024x1024","n":1,"prompt_extend":true}'
```

Billing de edicion: fee = precio x imagenes_input + precio x imagenes_output (las entradas
TAMBIEN facturan; las fallidas no).

## Modelos WAN (asincronos) — resumen

- Todos los Wan de imagen soportan llamada asincrona; `wan2.7-image-pro`, `wan2.7-image`,
  `wan2.6-image`, `wan2.6-t2i` tambien sincrona.
- Flujo async: POST crea tarea → `output.task_id` (valido 24 h) → GET `/tasks/{task_id}` →
  `output.task_status` (PENDING → SUCCEEDED/FAILED) → imagen en choices. Poll: 3 s los primeros
  30 s, luego espaciar; timeout ~2 min.
- Wan 2.7 exclusivos: `enable_sequential` (sets coherentes 1-12), `thinking_mode` (default true;
  solo con sequential=false), `color_palette` (3-10 colores {hex, ratio%}, suman 100%; solo
  sequential=false). Shorthand de size "1K"/"2K"/"4K" (4K solo pro). Sin `negative_prompt` ni
  `prompt_extend`.
- Endpoints y body exactos de Wan: https://docs.qwencloud.com/api-reference/image-generation/wan27-image-gen-edit/create-task
  (no adivinar; consultar).

## Errores

| Codigo/HTTP | Significado | Manejo |
|---|---|---|
| 429 / `Throttling.*` | Rate limit (util: pro 5 RPM / 10 concurrentes) | Backoff: esperar y reintentar |
| 401 / `InvalidApiKey` | Key mala/ausente o key↔host equivocados | `sk-sp-*` ⇒ host `token-plan.maas.qwencloudapi.com` |
| 400 / `DataInspectionFailed` | Moderacion (prompt, negative o imagen) | Reescribir prompt / quitar imagen de marca real |
| 400 `InvalidParameter` / `Model not exist` | Parametro fuera de rango o modelo fuera del plan | Ver tabla de parametros; TP: 3 modelos de imagen |
| `Arrearage` | Saldo pendiente (pay-as-you-go) | Regularizar pago |

Catalogo completo: https://docs.qwencloud.com/api-reference/preparation/error-messages

## Ejemplos de prompts (de la doc oficial)

**Texto complejo**: 'Bookstore window display. A sign displays "New Arrivals This Week". Below, a shelf tag with the text "Best-Selling Novels Here"... four books on the bookshelf, namely "The light between worlds" "When stars are scattered" "The silent patient" "The night circus"'

**Poster**: 'Healing-style hand-drawn poster featuring three puppies playing with a ball on lush green grass... The main title "Come Play Ball!" is prominently displayed at the top in bold, blue cartoon font...'

**Layout denso (infografia)**: 'Create a classroom PPT slide... Center title: "Habits for Emotional Wellbeing", surrounded by a symmetrical floral pattern. Left upper: "Practice Mindfulness" + minimalist lotus icon + text...'

**Fotorealista**: 'A realistic, high-fashion street-style photograph of a young Asian woman... neon-lit city street at night... overlayed text reads "Neon Dreams"... masterpiece, ultra-detailed, 8K, UHD, sharp focus'

**Edicion multi-fusion** (doc edit): 'The girl in Image 1 wears the black dress from Image 2 and sits in the pose from Image 3.' — casos documentados: fusion multi-imagen, consistencia de
sujeto, dibujo a partir de esqueleto/depth map/keypoints, edicion de texto dentro de la imagen,
anadir/quitar/reemplazar, cambio de punto de vista, restauracion de fotos viejas.

Patron: sujeto → detalles por zonas de la composicion → iluminacion → estilo/medio → texto
literal entre comillas → calidad. Guia completa:
https://docs.qwencloud.com/developer-guides/accuracy-tuning/image-generation
