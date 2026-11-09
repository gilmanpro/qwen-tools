---
name: qwen-web-search
description: >
  Busqueda web en tiempo real con QwenCloud (tool web_search de la Responses API, key
  sk-sp- del Token Plan resuelta sola desde auth.json): hechos/actualidad, clima,
  noticias, precios, fact-check, datos frescos con fuentes citables (action.sources).
  Usa SIEMPRE que el usuario pida buscar en internet con Qwen, verificar un dato actual
  o responder con fuentes citadas, aunque no nombre la herramienta. Sale del presupuesto
  diario compartido de 30 busquedas web+imagen (exit 3 al agotarse). NO para: buscar
  FOTOS por texto o imagen inversa → skill qwen-image-search; leer el contenido
  COMPLETO de una URL concreta → skill qwen-web-extractor (o webfetch/curl gratis).
license: MIT
metadata:
  version: "3.0"
  split-de: "qwen-tools v2.0"
  api_base_responses: "https://token-plan.maas.qwencloudapi.com/compatible-mode/v1"
---

# QWEN-WEB-SEARCH — busqueda web con fuentes (Responses API `web_search`)

Busqueda web agentica sobre la **Responses API** de QwenCloud: el modelo decide cuando
buscar, lanza N consultas y responde con texto + fuentes citables. Un script
solo-stdlib (sin `pip install`) que imprime UN unico JSON: `scripts\buscar_web.py`.

**REGLA DURA DEL HARNESS**: las tools del proveedor (`web_search`, `web_search_image`,
`image_search`, `web_extractor`, `code_interpreter`) **SOLO se invocan via Responses API**
(`POST {base}/responses`). En Chat Completions estas tools del `tools[]` NO disparan el
harness: quedan ignoradas. Las vias Chat/DashScope de este documento usan el mecanismo
`enable_search` (distinto, con otras reglas) y se documentan solo como referencia.

## DISPATCH (leer primero)

| Que necesitas | Camino |
|---|---|
| Respuesta con fuentes citables desde CLI (default) | `scripts\buscar_web.py` (Responses API, sin stream) |
| Control fino de estrategia (`turbo`/`max`/`agent`/`agent_max`) en Chat/DashScope | secciones ESTRATEGIAS y VIAS ALTERNATIVAS abajo (documental) |
| Leer el contenido COMPLETO de una URL concreta | skill `qwen-web-extractor` (`web_extractor`) |
| Fotos por texto / imagen inversa | skill `qwen-image-search` |

## COMO INVOCAR (ruta canonical)

```
py "%USERPROFILE%\.config\opencode\skills\qwen-web-search\scripts\buscar_web.py" --query "clima en Madrid hoy" --json
py "%USERPROFILE%\.config\opencode\skills\qwen-web-search\scripts\buscar_web.py" --query "X" --n 3 --answer short
py "%USERPROFILE%\.config\opencode\skills\qwen-web-search\scripts\buscar_web.py" --query "X" --model qwen3.8-max
```

Modelo default del script: `qwen3.8-flash` (funciona y es el mas barato; `qwen3.8-max`
sube la calidad del retrieval). Flags: `--query` (obligatoria), `--model`, `--base-url`
(salta la cadena), `--timeout` (120 s), `--json`, `--n` (recorte client-side de
sources[], default 5; 0 = todos), `--answer full|short|no`, `--max-uses` (param no
listado: si el endpoint lo rechaza con 400 se reintenta sin el campo),
`--max-searches-dia` (default 30; 0 = sin limite).

## CUANDO ACTIVAR (politica de ahorro — default OFF)

La busqueda **cuesta Credits** y contenido web recuperado **sube los input tokens**. No
la uses por iniciativa propia: vias gratuitas primero (websearch/webfetch del arnes,
cache, ctx7). Ejecutar sin confirmar SOLO cuando el usuario lo pida explicitamente o el
dato sea imprescindible y ninguna via gratuita lo cubra (marcarlo en el reporte). El
`exit 3` de presupuesto agotado es **definitivo para el dia**: no reintentar.

## KEY Y BASES — resolucion automatica (Familia A — Responses API)

**Nunca imprimir la key ni el body** (stdout, stderr ni `--out`). Sin ninguna key → exit 2
con instruccion (crear key en https://home.qwencloud.com/api-keys).

1. `~/.local/share/opencode/auth.json` → providers `alibaba-token-plan` / `-cn` (key
   `sk-sp-*`) → **cadena de bases** probada en orden hasta responder en `/responses` sin
   401/404/405 (el JSON registra la que funciono en `base`):

| Base candidata | Orden | Estado / fuente |
|---|---|---|
| `https://token-plan.maas.qwencloudapi.com/compatible-mode/v1` | 1 | **documentada del Token Plan** (docs regions/quickstart TP; las bases TP NO llevan region ID) — **200 verificada en vivo 2026-11-09** (evidencia `.tmp\qwen-split\tests\`; 7/7 llamadas ganaron esta base) |
| `https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1` | 2 | legacy — **fallback, no necesaria desde 2026-11-09** (200 empirico 2026-10-07; NO aparece en la doc) |
| `https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1` | 3 | empirica: 401 con la key sk-sp- actual (queda para otras keys/workspace) |

2. `ANTHROPIC_AUTH_TOKEN` si empieza por `sk-sp-` → misma cadena. 3. `DASHSCOPE_API_KEY`
(pay-as-you-go `sk-*`) → `https://maas.qwencloudapi.com/compatible-mode/v1`. 4.
`--base-url` manda sobre todo (usa solo esa base, sin cadena).

**Allowlist Token Plan** (`sk-sp-*`): cualquier otro modelo → `Model not exist`. El
consumo se liquida en **Credits** del plan; los USD de la tabla de fees son referencia de
costo relativo. Key `sk-sp-*` orientada a uso **interactivo**; lotes/produccion → key
pay-as-you-go. El Token Plan opera en **region Singapur**: las opciones regionales (fees,
modelos soportados) son las de la fila Singapur de la doc.

## FUENTES (como salen en cada via)

| Via | Fuentes |
|---|---|
| Responses API (esta skill) | items `web_search_call` → `action.query`/`action.queries` + `action.sources[].url`. **Sin marcadores [1]**: `enable_source`, `enable_citation`, `citation_format` y `search_strategy` NO existen en Responses (se ignoran en silencio) |
| DashScope (text/multimodal) | `search_options: {"enable_source": true}` → `search_info.search_results` (`index`, `title`, `url`) + marcadores [n] en el texto |
| Chat Completions compatible | **NO devuelve fuentes citables** (la doc lo desaconseja para citas) |

Regla para el agente: cita SIEMPRE las `sources` del JSON; si `sources: []` con `ok:true`
(el modelo decidio no buscar), decilo y propone una consulta mas concreta.

## ESTRATEGIAS `search_strategy` (vias Chat/DashScope — referencial)

`enable_search: true` + `search_options.search_strategy`:

- **`turbo`** (default): equilibrio velocidad/calidad. Para consultas del dia a dia.
- **`max`**: busqueda mas comprehensiva (multiples motores); mas lento.
- **`agent`**: retrieval agentico multi-vuelta (el modelo busca varias veces e integra).
  Soportada por las series Qwen3.5/3.6/3.7 (+open-source y Omni; Omni solo con `agent`).
  La **serie Qwen3.8 NO soporta `agent` por la via multimodal** (turbo/max): para
  retrieval agentico con 3.8 usa **la Responses API** (el camino de este script, que se
  factura igual que `agent`). Con `agent`/`agent_max` solo se admite `enable_source:true`;
  exige stream en el endpoint de texto.
- **`agent_max`**: `agent` + lectura de paginas completas via web extractor. **Solo
  qwen3.7-max en modo thinking.** (Equivalente recomendado hoy: Responses con tools
  `web_search` + `web_extractor` → skill `qwen-web-extractor`.)

**Via multimodal** (`multimodal-generation`, modelos con input imagen/video): la busqueda
web **exige `stream=True`** (sin stream: `Non-streaming mode does not support Web Search`)
y responde 400 `url error` si se llama por `text-generation`. Java SDK: inyecta
`search_options` via `parameter("search_options", ...)`.

## MODELOS SOPORTADOS (web_search, extracto de la doc)

Qwen3.8 (max, max-0902, flash, open-source; sin `agent` en via multimodal), Qwen3.7
(max/plus/flash), Qwen3.6, Qwen3.5 (+omni, strategy fija `agent`), deepseek-v4 /
v4.1-flash, glm-5.2 (solo Responses), kimi-k3 (solo Responses) y kimi-k3.1-pro (Responses
+ Anthropic). Regiones: SG, Beijing-N2, Frankfurt, HK, Tokyo, Virginia — **TP = Singapur**.

## PRESUPUESTO DIARIO — contador compartido

Fichero UNICO `skills\.qwen_uso_diario.json` (lo resuelve `parents[2]` del script; due-
ño de ninguna skill, sobrevive al split), formato
`{"fecha":"YYYY-MM-DD","web":N,"imagen":N,"extractor":N}`. Limite combinado
**web+imagen >= 30/dia** (flag `--max-searches-dia`) → `exit 3` con
`{"ok":false,"budget_exceeded":true,...}` **sin lanzar HTTP**. El bucket `extractor` es
informativo (web_extractor es gratis por tiempo limitado): NO consume el limite. Reglas:
otra fecha = reinicio automatico; solo suman llamadas CON exito
(`usage.x_tools.web_search.count`); fallo de red NO suma; ausente/corrupto = 0 y se
recrea; escritura atomica tmp+rename; reset = borrar el archivo.

## CONTRATO DE SALIDA (UN JSON unico en stdout; diagnosticos por stderr)

```json
{ "ok": true, "query": "…", "answer": "…", "sources": ["https://…"],
  "searches": ["consulta lanzada por el modelo"], "usage": {"input_tokens": 7331,
  "output_tokens": 1051, "x_tools": {"web_search": {"count": 2}}}, "seconds": 28.9,
  "base": "https://token-plan.maas.qwencloudapi.com/compatible-mode/v1",
  "mode": "web_search" }
```

Error: `{"ok":false,"error":{...},"http_status":N,"attempted":[{base,http,err}...]}`.
Exit codes: `0` OK · `1` API/red tras agotar cadena y reintentos · `2` configuracion/uso
(falta key/query, flag invalido) · `3` presupuesto agotado (definitivo por el dia).
Reporta SIEMPRE `base` + `usage` (1 linea, trazabilidad de Credits).

## FEES (list price — Token Plan lo cobra en Credits)

| Herramienta | Fee | Notas |
|---|---|---|
| `web_search` (Responses) | **$10.00 / 1.000 llamadas Singapur** · $0.573411 / 1k en Beijing-N2, Frankfurt, HK, Tokyo, Virginia | Responses se factura como estrategia `agent`; el contenido web sube los input tokens (precio estandar del modelo) |

**NOTA FAQ (auditoria)**: `usage.count` (`x_tools` en OpenAI-compat, `plugins.search` en
DashScope) mide la **intencion de busqueda detectada**, NO es base de facturacion ni
conciliacion: la busqueda se factura cuando la recuperacion real termina con exito. Usa
la factura/saldo de Credits como fuente autoritativa. Un 429 o una busqueda sin resultados
tambien dejan `count` != 0.

## ERRORES

| Situacion | Accion |
|---|---|
| HTTP 429 / `Throttling*` | el script reintenta 2x (5 s/10 s); persiste → esperar 1 min y reducir ritmo |
| HTTP 401 / `InvalidApiKey` | key invalida o key↔host incorrectos (`sk-sp-*` ⇒ hosts token-plan). Detenerse |
| `Model not exist` | modelo fuera de la allowlist del Token Plan |
| HTTP 400 `InvalidParameter` | parametro fuera de rango o `max_uses` rechazado (el script reintenta solo sin el campo) |
| exit 3 `budget_exceeded` | presupuesto diario agotado: NO reintentar hoy (reset: borrar `skills\.qwen_uso_diario.json`) |
| `sources: []` con `ok:true` | el modelo decidio no buscar: valido, proponer consulta mas concreta |
| Timeout | consulta muy compleja → dividir en partes o subir `--timeout` |

## ARCHIVOS

```
qwen-web-search/
├── SKILL.md
├── README.md
├── scripts/
│   └── buscar_web.py            # Responses API web_search (stdlib, contador parents[2])
└── references/
    └── api-web-search.md        # detalle API: bodies, items, estrategias, fees, FAQ
```

Leer la reference SOLO cuando el cuerpo de esta skill no baste (body literal, casos raros).
Fotos → `qwen-image-search`; paginas completas → `qwen-web-extractor`.
