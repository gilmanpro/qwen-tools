# QwenCloud — Web extractor (leer paginas completas: `web_extractor` / `web_fetch` / `agent_max`)

Fuentes (consultadas 2026-11-09, doc oficial en vivo):
- https://docs.qwencloud.com/developer-guides/tool-calling/web-scraping (pagina oficial "Web extractor")
- https://docs.qwencloud.com/developer-guides/tool-calling/web-search (estrategias, fee search)

## REGLA DURA DEL HARNESS

Las tools del proveedor (`web_search`, `web_search_image`, `image_search`,
`web_extractor`, `code_interpreter`) **SOLO se invocan a traves de la Responses API**
(`POST {base}/responses`): en Chat Completions un `tools[]` con estas types **NO dispara
el harness**. Las otras dos vias de esta pagina no usan `tools[]` con `web_extractor`:
usan los mecanismos `search_strategy: "agent_max"` (Chat/DashScope) o la tool Anthropic
`web_fetch`.

## Las 4 formas de invocar web extractor (tabla de la doc)

| API | Configuracion | Stream requerido | Notas |
|---|---|---|---|
| **Responses API (recomendada)** | `tools: [{"type":"web_search"},{"type":"web_extractor"}]` | **No** | Expone el estado de ejecucion intermedio de cada tool; maximo control; **la via del script `extraer_web.py`** |
| Chat Completions API | `enable_search: true` + `search_strategy: "agent_max"` | **Si** | Non-streaming no soportado |
| DashScope API | idem Chat (`enable_search` + `agent_max`) | **Si** | Java SDK no soportado |
| Anthropic-compatible | `tools` con `web_search` y `web_fetch` (aqui el extractor se llama **web_fetch**) | No | Apuntado a clientes Anthropic (Claude Code y similares) |

`agent_max` = estrategia `agent` (retrieval agentico multi-vuelta) **mas lectura de
paginas completas con el extractor**; **solo disponible en qwen3.7-max en modo thinking**;
con `agent`/`agent_max` solo se admite `enable_source: true` (demas funciones de busqueda
no disponibles). Para qwen3.7-max en Chat/DashScope la doc exige `enable_thinking: true`.

**Bases para las vias**: Token Plan (key `sk-sp-*`) — Responses/Chat compat
`https://token-plan.maas.qwencloudapi.com/compatible-mode/v1`; **Anthropic-compatible TP**
`https://token-plan.maas.qwencloudapi.com/apps/anthropic` (`/v1/messages`). Pay-as-you-go
(p. ej. los ejemplos de la doc en Singapur): `https://ap-southeast-1.maas.qwencloudapi.com/compatible-mode/v1`.

## Body literal Responses API (lo que envia el script)

```json
POST {base}/responses
{
  "model": "qwen3.8-max",
  "input": "Please visit https://example.com/article and summarize it",
  "tools": [
    {"type": "web_search"},
    {"type": "web_extractor"}
  ]
}
```

La doc de arranque usa `qwen3.8-max` **en thinking mode** (`extra_body {"enable_thinking":
True}` en el SDK; en Responses puro, `enable_thinking` esta deprecated → `reasoning.effort`).
El script default `qwen3.8-flash` (qwen3.8-flash figura en "Recommended models — Qwen-Flash"
de la doc web extractor) y no envia flags de thinking. El input puede ser string (las URLs
van escritas en el texto del prompt) — el script añade las `--url` como bloque "URLs de
interes" debajo del `--prompt`. `web_search` acompanante es el patron recomendado por la
doc ("typically accompanied"); para enviar solo el extractor, `--sin-web-search`.

Flujo (doc "How it works"): 1) incluye las tools + un prompt que referencia URL o tema;
2) **el modelo determina que paginas leer**, las recupera y añade su contenido como input
tokens adicionales; 3) genera la respuesta anclada en lo recuperado. Es decir: las URLs
del prompt son referencia, no una garantia de descarga — el modelo decide.

## Estructura de la respuesta (doc "Response structure")

| Campo | Descripcion |
|---|---|
| `output_text` (via item `message`) | respuesta final del modelo, anclada al contenido extraido |
| `output[]` | items intermedios incluidos **`web_extractor_call`**: cada uno con campos **`goal`** (que se pretendia leer) y **`output`** (contenido extraido; string JSON o texto) + `status` |
| `usage.x_tools.web_extractor.count` | numero de invocaciones del extractor en la request |
| `usage.x_tools.web_search.count` | numero de invocaciones de busqueda (la interna del extractor cuenta aqui) |

## Streaming (Responses API)

La extraccion puede tardar; streaming solo si te interesa el progreso. Eventos especificos
(doc): `response.reasoning_text.delta` (razonamiento incremental) ·
`response.output_item.done` (tool terminada — mirar `item.type == "web_extractor_call"` y
leer sus campos `goal`/`output`) · `response.output_text.delta` (texto) ·
`response.completed` (`usage` con los counts de tools). Patron literal de la doc:

```python
for chunk in stream:
  if chunk.type == 'response.output_item.done':
    if hasattr(chunk, 'item') and chunk.item.type == 'web_extractor_call':
        print(f"Fetched: {chunk.item.goal}")
        print(f"Content: {chunk.item.output}")
  elif chunk.type == 'response.output_text.delta':
    print(chunk.delta, end='', flush=True)
  elif chunk.type == 'response.completed':
    usage = chunk.response.usage
    print(usage.x_tools.get('web_extractor', {}).get('count', 0))
```

El script NO usa stream (Responses no lo requiere; una sola llamada y parseo completo).

## Modelos soportados (doc 2026-11-09)

Recomendados Responses: Qwen-Max (3.8-Max, 3.7-Max), Qwen-Plus (3.7/3.6/3.5-Plus),
**qwen3.8-flash**, DeepSeek (v4.1-flash, v4.1-flash-1017, v4-pro-0813, v4-flash-0731,
v4-pro), GLM glm-5.2, Kimi kimi-k3, serie open-source Qwen3.8.
Otros (solo Responses, rendimiento menor): Qwen3.8/3.7/3.6/3.5-Flash, qwen3.8-2.4t-a95b,
open-source 3.6 (salvo 27b) y 3.5, deepseries y glm-5.2 repetidos.
Chat Completions/DashScope (`agent_max`): **solo Qwen3.7-Max thinking** (+ Qwen3.5-Plus
listado en "recommended" para la via Chat).
Regiones: deepseek-v4.1-flash-1017 y kimi-k3.1-pro tienen `web_extractor` (Responses) y
`web_fetch` (Anthropic) en **todas** las regiones (SG, Beijing-N2, Frankfurt, HK, Tokyo,
Virginia).

## Combinar con code_interpreter

Doc: "For tasks involving mathematical calculations or data analytics, add
`code_interpreter` alongside web extractor to improve accuracy." O sea
`tools: [{"type":"web_search"},{"type":"web_extractor"},{"type":"code_interpreter"}]` —
solo Responses; recuerda que code_interpreter es EXCLUYENTE con function calling
(skill qwen-code-interpreter).

## Limitaciones (doc "Limitations" — texto literal resumido)

- Recupera **solo paginas publicamente accesibles**: tras autenticacion o paywall
  devuelve **contenido vacio**.
- Paginas muy grandes pueden **truncarse** antes de anadirse al contexto (en Responses el
  context util ronda el 80% de la ventana por el buffer de tools; truncado silencioso).
- Contenido **renderizado solo por JavaScript** puede no capturarse completamente.
- El contenido extraido **cuenta como input tokens**: mas latencia y mas coste en
  paginas grandes.

## Error handling (doc) — la extraccion fallida NO es error

Cuando la extraccion falla el modelo **no levanta error**: el item `web_extractor_call`
devuelve contenido **vacio o parcial** y la respuesta se genera con el contexto
disponible. Verificacion: inspeccionar los items `web_extractor_call` en `output` o el
`usage.x_tools.web_extractor.count`.

| Escenario | Comportamiento |
|---|---|
| URL unreachable (404, 500, DNS) | extraccion vacia; el modelo responde con otro contexto |
| Timeout de carga de pagina | contenido parcial o vacio |
| Contenido no-HTML (PDF, imagenes) | puede no extraerse; fallback a otras tools o conocimiento general (para PDF → skill qwen-pdf) |

## Billing (doc "Billing")

| Componente | Detalle |
|---|---|
| Coste de modelo | el contenido extraido se anade al prompt → **aumenta los input tokens**; precio estandar del modelo |
| **Fee de web search** | **$10.00 por 1.000 llamadas en Singapur; $0.573411 por 1k en Beijing-N2, Frankfurt, HK, Tokyo y Virginia.** "Web extractor typically triggers web search internally" |
| **Fee de web extractor** | **gratis por tiempo limitado** |

Token Plan (`sk-sp-*`): todo se liquida en **Credits** del plan (los USD son lista/
referencia). TP opera en region Singapur. Nota FAQ identica a web-search: los `count` de
`usage` no son base de facturacion ni conciliacion (la busqueda se factura cuando la
recuperacion termina con exito; `count` refleja la intencion detectada).

## Cuando usar una cosa u otra (guia de eleccion rapida)

| Necesitas | Herramienta / skill |
|---|---|
| Leer **esta URL** y responder sobre ella | `web_extractor` (+ `web_search`) — **esta skill** |
| Investigar un **tema** leyendo paginas completas | `web_search` + `web_extractor` — esta skill |
| Dato puntual **sin** URL concreta | `web_search` solo (skill `qwen-web-search`, mas barato y rapido) |
| Scrapear sin IA (HTML crudo) | webfetch/curl del arnes — gratis, local |
