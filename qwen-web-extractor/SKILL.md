---
name: qwen-web-extractor
description: >
  Lee el CONTENIDO COMPLETO de paginas web con QwenCloud (tool web_extractor de la
  Responses API, key sk-sp- del Token Plan resuelta sola): resumir/extraer/preguntar
  sobre 1+ URLs concretas, con items web_extractor_call (goal/output) y usage.
  web_extractor esta GRATIS por tiempo limitado (solo pagas los input tokens del
  contenido extraido + el fee interno de web_search si se lanza). Usa SIEMPRE que el
  usuario pida "leeme esta pagina y resumela", extraer el texto completo de una URL con
  IA de Qwen o responder preguntas ancladas a URLs dadas, aunque no nombre la
  herramienta. NO para: busqueda generica sin URL concreta → skill qwen-web-search;
  scrapear sin IA una URL publica → webfetch/curl del arnes (gratis, local); paginas
  con autenticacion/paywall o contenido renderizado solo por JavaScript (limitacion de
  la herramienta: devuelve vacio sin error).
license: MIT
metadata:
  version: "3.0"
  split-de: "qwen-tools v2.0"
  api_base_responses: "https://token-plan.maas.qwencloudapi.com/compatible-mode/v1"
---

# QWEN-WEB-EXTRACTOR — leer paginas completas (Responses API `web_extractor`)

La tool **`web_extractor`** hace que el modelo **lea paginas web completas** y responda
anclado a su contenido (no solo al snippet de una busqueda). Via recomendada: **Responses
API**, normalmente con `web_search` en el mismo `tools[]` (el modelo busca, elige paginas
y las lee en crudo). **Sin stream requerido** en Responses. Un script solo-stdlib:
`scripts\extraer_web.py`.

**REGLA DURA DEL HARNESS**: `web_extractor` (y las demas tools del proveedor:
`web_search`, `web_search_image`, `image_search`, `code_interpreter`) **SOLO se invocan
via Responses API** (`POST {base}/responses`); Chat Completions NO dispara el harness.
Las vias alternativas de abajo (Chat/DashScope `agent_max`, Anthropic `web_fetch`) son
mecanismos DISTINCTOS con sus propias reglas.

## DISPATCH — LAS 3 VIAS (leer primero)

| Via | Configuracion | Stream | Notas |
|---|---|---|---|
| **Responses API (RECOMENDADA — el script)** | `tools: [{"type":"web_search"},{"type":"web_extractor"}]` | **NO requerido** | Expone el estado intermedio de cada tool (items `web_extractor_call` con `goal`/`output`); maximo control |
| Chat Completions / DashScope | `enable_search: true` + `search_options: {"search_strategy": "agent_max"}` | **SI, exigido** (non-streaming no soportado) | `agent_max` = agent + lectura de paginas; **solo qwen3.7-max en modo thinking**; Java SDK no soportado en DashScope; con agent/agent_max solo se admite `enable_source:true` |
| Anthropic-compatible | `tools` con `web_search` + **`web_fetch`** (nombre del extractor aqui) | NO | Base TP `https://token-plan.maas.qwencloudapi.com/apps/anthropic`; apunta a clientes Anthropic (Claude Code y similares); deepseek-v4.1-flash-1017 y kimi-k3.1-pro la soportan en todas las regiones |

Para una integracion nueva: **Responses** (via del script). Casos de uso segun la doc:
pregunta sobre una **URL concreta** → `web_extractor` (+ `web_search` opcional);
investigar un **tema** a fondo → ambas tools; dato puntual sin URL → solo `web_search`
(skill `qwen-web-search`, mas barato y rapido).

## COMO INVOCAR (ruta canonical)

```
py "%USERPROFILE%\.config\opencode\skills\qwen-web-extractor\scripts\extraer_web.py" --url "https://example.com" --prompt "resume la pagina" --json
:: 1+ URLs: repetida o coma-separada
py ...extraer_web.py --url https://a.com --url https://b.com --json
py ...extraer_web.py --url "https://a.com,https://b.com" --prompt "compara los precios de ambas" --out .tmp\comparativa.json
:: enviar solo el extractor (sin web_search acompanante)
py ...extraer_web.py --url "https://ya-se.md" --sin-web-search
```

Flags: `--url` (obligatorio, 1+; `--url a --url b` o `"a,b"`), `--prompt` (default
"Extrae y resume el contenido de estas URLs"), `--model` (default `qwen3.8-flash`;
recomendado para maxima calidad `qwen3.8-max`), `--json`, `--out` (copia el JSON a una
ruta **dentro del proyecto**, nunca fuera), `--timeout` (default **180 s** — la
extraccion puede tardar), `--base-url`, `--respuesta full|short|no`,
`--sin-web-search`. Exit codes: `0` OK · `1` API/red tras agotar cadena · `2`
configuracion/uso (faltan URLs, URL no http(s), falta key). **El extractor NO consume el
presupuesto local de 30** (no existe exit 3 en esta via hoy).

## CUANDO ACTIVAR (politica de ahorro)

Gratis el extractor **por tiempo limitado**, PERO: el contenido extraido se anade al
prompt → **sube los input tokens** (factor real de coste, pagina grande = contexto
grande) y web_extractor **suele disparar web_search interno**, facturado a $10/1k
(Singapur) si se lanza. El script avisa por stderr cuando la respuesta trae
`x_tools.web_search.count > 0`. Scrapear una URL publica sin analisis → webfetch/curl
del arnes es GRATIS y local: usa el extractor solo cuando el modelo deba **leer y razonar**
sobre la pagina.

## KEY Y BASES — resolucion automatica (Familia A — Responses API)

**Nunca imprimir la key ni el body** (stdout, stderr ni `--out`). Sin ninguna key → exit 2
con instruccion (crear key en https://home.qwencloud.com/api-keys).

1. `~/.local/share/opencode/auth.json` → providers `alibaba-token-plan` / `-cn` (key
   `sk-sp-*`) → **cadena de bases** probada en orden hasta responder en `/responses` sin
   401/404/405 (el JSON registra la que funciono en `base`):

| Base candidata | Orden | Estado / fuente |
|---|---|---|
| `https://token-plan.maas.qwencloudapi.com/compatible-mode/v1` | 1 | **documentada del Token Plan** (fuente: docs regions/quickstart TP; las bases TP NO llevan region ID) — **200 verificada en vivo 2026-11-09** (evidencia `.tmp\qwen-split\tests\`; 7/7 llamadas ganaron esta base) |
| `https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1` | 2 | legacy — **fallback, no necesaria desde 2026-11-09** (200 empirico 2026-10-07; NO aparece en la doc) |
| `https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1` | 3 | empirica: 401 con la key sk-sp- actual (queda para otras keys/workspace) |

2. `ANTHROPIC_AUTH_TOKEN` si empieza por `sk-sp-` → misma cadena. 3. `DASHSCOPE_API_KEY`
(pay-as-you-go `sk-*`) → `https://maas.qwencloudapi.com/compatible-mode/v1`. 4.
`--base-url` manda sobre todo (usa solo esa base, sin cadena). Via Anthropic (documental):
base TP `https://token-plan.maas.qwencloudapi.com/apps/anthropic`.

**Allowlist Token Plan** (`sk-sp-*`): cualquier otro modelo → `Model not exist`. Consumo
en **Credits**. TP opera en **region Singapur** (la fila de fees SG de la doc es la que
aplica).

## LIMITACIONES DURAS (doc oficial — verificar siempre `extracted[]`)

- **Solo paginas publicas**: tras autenticacion o paywall devuelve **contenido vacio**.
- **Truncado**: paginas muy grandes pueden recortarse antes de entrar al contexto
  (en Responses el context util es ~80% de la ventana; el truncado es silencioso).
- **JavaScript dinamico**: contenido renderizado exclusivamente por JS puede no
  capturarse.
- **Extraction fail NO es error HTTP**: el item `web_extractor_call` sale con
  `goal`/`output` vacios o parciales y el modelo responde "con lo que haya" — `ok:true`
  puede esconder una extraccion vacia. **Verificar SIEMPRE `extracted[]` en el JSON**
  (y `usage.x_tools.web_extractor.count`) antes de dar por leida la pagina.
- URL unreachable (404/500/DNS) → contenido vacio; timeout de carga → parcial;
  contenido no-HTML (PDF, imagenes) → puede no extraerse (el modelo hace fallback; para
  PDFs usa la skill `qwen-pdf`).
- Contenido de paginas enormes sube latencia y coste (tokens).

## MODELOS SOPORTADOS (Responses API, extracto de la doc 2026-11-09)

Recomendados: Qwen3.8-Max series y Qwen3.7-Max (con `qwen3.7-max` poner
`enable_thinking: true` en Chat/DashScope), Qwen3.7/3.6/3.5-Plus, **qwen3.8-flash**
(default del script), deepseek-v4/v4.1-flash(-1017), glm-5.2, kimi-k3, serie open-source
3.8. Otros (solo Responses, menor rendimiento): series Flash 3.8/3.7/3.6/3.5,
qwen3.8-2.4t-a95b, open-source 3.6/3.5. deepseek-v4.1-flash-1017 y kimi-k3.1-pro also
tienen `web_extractor`/`web_fetch` en todas las regiones.

## PRESUPUESTO DIARIO — bucket `extractor` INFORMATIVO

El contador compartido `skills\.qwen_uso_diario.json` (resuelto como `parents[2]` del
script, formato `{"fecha":"YYYY-MM-DD","web":N,"imagen":N,"extractor":N}`) **suma** tras
cada exito `usage.x_tools.web_extractor.count` al bucket `extractor`, pero es
**INFORMATIVO**: web_extractor es gratis por tiempo limitado, **NO descuenta del limite
combinado de 30 web+imagen** ni bloquea nada. Cuando la doc oficial anuncie fee, se
activa el bloqueo cambiando el flag default `EXTRACTOR_BLOQUEA = True` del script. Las
demas reglas heredadas: otra fecha = reinicio; solo suman exitos; fallo de red NO suma;
ausente/corrupto = 0 y se recrea; escritura atomica tmp+rename; reset = borrar archivo.

## CONTRATO DE SALIDA (SPEC S4 — UN JSON unico en stdout; diagnosticos por stderr)

```json
{ "ok": true, "urls": ["https://example.com"], "prompt": "resume la pagina",
  "answer": "respuesta del modelo anclada al contenido",
  "extracted": [{"goal": "que queria leer", "output": "contenido extraido", "status": "completed"}],
  "extracciones": 1,
  "usage": {"input_tokens": 8123, "output_tokens": 456,
            "x_tools": {"web_extractor": {"count": 1}, "web_search": {"count": 0}}},
  "seconds": 34.2, "base": "https://token-plan.maas.qwencloudapi.com/compatible-mode/v1",
  "mode": "web_extractor" }
```

Error: `{"ok":false,"error":{...},"http_status":N,"attempted":[...]}`. El `count` de
`usage.x_tools` mide intencion de uso, **no es base de facturacion** (misma nota FAQ que
web_search): reconciliar contra factura/saldo de Credits.

## ERRORES

| Situacion | Accion |
|---|---|
| `extracted: []` o con `output` vacio y `ok:true` | la herramienta NO erro: pagina privada/JS-only/unreachable. Verificar la URL en el navegador; probar `--sin-web-search` o URL alternativa (NO dar la pagina como "leida") |
| HTTP 429 / `Throttling*` | el script reintenta 2x (5 s/10 s); persiste → esperar 1 min |
| HTTP 401 / `InvalidApiKey` | key invalida o key↔host (`sk-sp-*` ⇒ hosts token-plan). Detenerse |
| `Model not exist` | modelo fuera de la allowlist del Token Plan |
| HTTP 400 `InvalidParameter` | prompt/URL malformed; revisar `error.message` del JSON |
| Respuesta larga / timeout | paginas grandes: subir `--timeout` (>180 s) o reducir a 1 URL por llamada |
| Streaming wanted | events `response.output_item.done` con `item.type=="web_extractor_call"` (goal/output) y `response.completed` (usage) — la doc de la reference tiene el patron |

## ARCHIVOS

```
qwen-web-extractor/
├── SKILL.md
├── README.md
├── scripts/
│   └── extraer_web.py           # Responses API web_extractor (+web_search) — stdlib, contador parents[2]
└── references/
    └── api-web-extractor.md     # detalle API: bodies 3 vias, items, streaming, limites, fees
```

Leer la reference SOLO cuando el cuerpo de esta skill no baste. Buscar sin URL →
`qwen-web-search`; PDFs → `qwen-pdf`.
