# QwenCloud — Image search (Responses API: `web_search_image` / `image_search`)

Fuentes (consultadas 2026-11-09, docs oficiales en vivo + pruebas propias):
- https://docs.qwencloud.com/developer-guides/tool-calling/image-search
- https://docs.qwencloud.com/developer-guides/multimodal/vision (limites de input)
- Pruebas reales 2026-10-07 (smoke tests del script original).

Ambas tools existen **SOLO en la Responses API** (`POST {base}/responses`) y **SOLO en las
regiones Singapur y China North 2 (Beijing)** — el **Token Plan opera en Singapur**, o sea
que con key `sk-sp-*` la condicion regional se cumple **de fabrica**.

**REGLA DURA DEL HARNESS**: `web_search_image` / `image_search` / `web_search` /
`web_extractor` / `code_interpreter` solo se disparan via `/responses`; en Chat
Completions el `tools[]` con estas types NO invoca el harness.

## Bases URL (autenticacion)

Precedencia (`buscar_imagen.py`, identica a `buscar_web.py`):

1. `~/.local/share/opencode/auth.json` provider `alibaba-token-plan` / `-cn` (`sk-sp-*`)
   → cadena TP en orden:

| # | Base | Estado / fuente |
|---|---|---|
| 1 | `https://token-plan.maas.qwencloudapi.com/compatible-mode/v1` | **documentada del Token Plan** (fuente: docs regions/quickstart TP; sin region ID en la URL) — **200 verificada en vivo 2026-11-09** (evidencia `.tmp\qwen-split\tests\`; 7/7 llamadas ganaron esta base) |
| 2 | `https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1` | **legacy — fallback, no necesaria desde 2026-11-09** (200 empirico 2026-10-07; NO aparece en la doc) |
| 3 | `https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1` | empirica: 401 con la sk-sp- actual (Beijing-N2 es region valida para estas tools: sirve para keys de workspace Beijing) |

   (Retirada de la cadena: `ws-<ID-workspace>...maas.aliyuncs.com/api/v1` — 404
   permanente verificado y sin respaldo documental.)
2. `ANTHROPIC_AUTH_TOKEN` (`sk-sp-*`) → misma cadena. 3. `DASHSCOPE_API_KEY` (pay-as-you-go)
→ `https://maas.qwencloudapi.com/compatible-mode/v1` — la key es regional: solo funciona
si pertenece a workspace Singapur o Beijing-N2. 4. `--base-url` manda.

## Bodies literales

### Texto → imagenes (`web_search_image`)

```json
POST {base}/responses
{
  "model": "qwen3.8-flash",
  "input": "gato siames",
  "tools": [{"type": "web_search_image"}]
}
```

El modelo decide cuando buscar segun el input.

### Imagen → imagenes similares (`image_search`)

`input` es una lista de contenido; el `input_text` es opcional (contexto para afinar):

```json
POST {base}/responses
{
  "model": "qwen3.8-flash",
  "input": [
    {"role": "user", "content": [
      {"type": "input_text", "text": "Find landscape images with a similar style to this one"},
      {"type": "input_image", "image_url": "https://img.alicdn.com/imgextra/.../ejemplo.png"}
    ]}
  ],
  "tools": [{"type": "image_search"}]
}
```

`image_url` acepta URL publica **o data URI base64** (`data:image/png;base64,...`;
verificado). La **SDK de OpenAI no acepta rutas locales**: el script convierte la ruta
local a data URI automaticamente (limite suave 20 MB). Las imagenes muy pequenas (>10 px
de lado minimo) o una URL que el servidor no logra descargar → 400 `InvalidParameter`
(p. ej. "Download multimodal file timed out"). Formatos y limites de input: seccion
"Input file limits" de la guia de vision.

## Estructura de la respuesta (doc + pruebas reales)

`output` = array con items intercalados:

- `type: "web_search_image_call"` / `"image_search_call"`:
  - `name`: `web_search_image` / `image_search`.
  - `status`: `completed` etc.
  - `arguments`: string JSON `{"queries": ["...", ...]}` (modo texto; puede faltar).
  - `output`: **string con un array JSON** `[{index,title,url}, ...]` — max **100**
    resultados por busqueda (la cantidad la decide el modelo, no es fija). Puede
    faltar/ser null.
- `type: "message"` — analisis del modelo sobre los resultados: partes
  `{"type":"output_text","text":...}`.
- `type: "reasoning"` — trazas (no se usan).

`usage.x_tools`: `{"web_search_image": {"count": N}}` o `{"image_search": {"count": N}}`.
El modelo busca **una imagen a la vez** pero puede invocar la tool varias veces en una
misma respuesta para cubrir varias imagenes; el numero de resultados por busqueda lo fija
el modelo (tope 100).

Si ninguna busqueda se dispara (input poco informativo), sale `status: completed` sin item
`*_call`, `sources=[]` y `usage.x_tools` ausente → el script devuelve `ok:true` con lista
vacia (no es error).

## Modelos soportados (doc 2026-11-09; solo Responses API)

- Recomendados: Qwen3.7/3.6/3.5-Plus series, Qwen3.8-Max series, qwen3.7-max-2026-06-08,
  qwen3.8-27b.
- Tambien funcionan con menor rendimiento: series Qwen3.8-Flash / 3.7-Flash / 3.6-Flash /
  3.5-Flash (qwen3.8-flash verificado en prueba real con count=1).

## Streaming (opcional — el script no lo usa)

`stream=True` emite en orden: `response.output_item.added` (arranca la tool) →
`response.output_item.done` (parsear `item.output` como JSON) → `response.content_part.added` →
`response.output_text.delta` → `response.completed` (`usage` final). Util para progreso en
UI; el script hace una sola llamada no-stream y listo.

## Billing (list price; promociones en www.qwencloud.com/models)

| Carga | Detalle |
|---|---|
| Fee de tool | **$8.00 / 1.000 llamadas Singapur · $6.881 / 1.000 Beijing-N2** (ambas tools) |
| Tokens modelo | los resultados de busqueda se anaden al prompt → sube input tokens (precio estandar) |

**Token Plan**: se descuenta en **Credits**, no en factura pay-as-you-go; los USD son
referencia de costo relativo.

## Rate limits (429)

Throttling → HTTP 429; el script reintenta 2 veces (5 s / 10 s). Persiste → reducir ritmo
(policy TP: esperar ~1 min).
