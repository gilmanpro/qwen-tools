---
name: qwen-mcp
description: >
  Conecta el modelo QwenCloud a un servidor MCP externo (Model Context Protocol) via la
  tool {type:"mcp"} de la Responses API con server_protocol "sse": el modelo lista y usa
  las herramientas del servidor (scraping fetch, buscadores, datos de terceros) y responde
  con sus resultados. SOLO con URL SSE proporcionada por el usuario — el script
  consultar_mcp.py NUNCA improvisa endpoints (sin --server-url → exit 2 sin HTTP). Max 10
  servers por request; billing = tokens del modelo + fees del proveedor del server. Usar
  cuando el usuario de su endpoint SSE MCP y pida usarlo con Qwen. NO para: function
  calling con herramientas locales → qwen-function-calling; servers stdio (no soportados);
  scrapeo de una URL suelta → qwen-web-extractor.
license: MIT
metadata:
  version: "3.0"
  split-de: "qwen-tools v2.0"
  api_base_responses: "https://token-plan.maas.qwencloudapi.com/compatible-mode/v1"
---

# QWEN-MCP — Servidores MCP externos (Responses API, solo SSE)

La plataforma QwenCloud hace de cliente MCP: declaras el servidor en `tools` del request
`/responses` y el modelo conecta por SSE, lista las herramientas y las llama; los
resultados entran en su contexto y la respuesta final los integra. Script
`scripts\consultar_mcp.py` solo-stdlib con contrato JSON.

## ⚠️ CAUCION Token Plan (F2b-3 2026-11-09 — TRAMPA 200, leer antes de prometer nada)

> **Con `sk-sp-` la tool `mcp` es ACEPTADA (HTTP 200) pero queda SILENCIADA**: la respuesta
> llega `ok:true` con `mcp_calls: []` e input de solo ~109 tokens — las herramientas del
> servidor JAMAS se inyectan en el contexto (el ejemplo oficial de la doc consume ~20k de
> input). Es una **TRAMPA 200 analoga a PDF-en-Responses**: NO hay 4xx que te avise.
> **Evidencia:** `.tmp\qwen-split\tests\qwen-mcp\consultar_mcp.json` (endpoint SSE real
> `amap-maps` de la doc oficial, base TP documentada, `input_tokens: 109`, `mcp_calls: []`).
> **Regla:** con `sk-sp-` NO usar el modo interactivo esperando tools MCP; para MCP real usar
> key pay-as-you-go (`sk-*` / `sk-ws-*` con saldo). Si el usuario solo tiene TP, proponer
> `qwen-web-extractor` (URLs) o function calling local (`qwen-function-calling`).

## REGLA DE ORO: la URL SSE la aporta el USUARIO

- El endpoint SSE vive en la plataforma que aloja el servidor (p. ej. ModelScope →
  pestana "Service configuration" del server, con su token de auth si lo pide).
- El script **nunca inventa ni adivina endpoints**: sin `--server-url` → JSON
  `{"ok":false,"error":"falta_server_url"}` + **exit 2 SIN lanzar HTTP** (verificado).
- Si el usuario no da URL: pedirsela; no improvisar.

## LA TOOL `mcp` (doc oficial 2026-11-09)

```json
{
  "type": "mcp",
  "server_protocol": "sse",
  "server_label": "fetch",
  "server_description": "Fetch MCP Server que provee capacidades de web scraping. Puede extraer el contenido de una URL especificada y devolverlo como texto.",
  "server_url": "https://mcp.api-inference.modelscope.net/xxx/sse",
  "headers": {"Authorization": "Bearer <token-de-la-plataforma>"}
}
```

| Parametro | Obligatorio | Notas |
|---|---|---|
| `type` | SI | siempre `"mcp"` |
| `server_protocol` | SI | **UNICO valor soportado: `"sse"`** |
| `server_label` | SI | nombre identificador del server |
| `server_url` | SI | endpoint SSE del servidor |
| `server_description` | recomendado | describe capacidades; mejora la precision de la eleccion de herramienta |
| `headers` | no | cabeceras al conectar (p. ej. `Authorization` con el token de la plataforma) |

- **Maximo 10 servers MCP por request** (varias entradas `type:"mcp"` en `tools`).
- **SOLO Responses API** (`/responses`): MCP no existe en Chat Completions.
- Stream recomendado: las llamadas MCP implican multiples interacciones con el servicio
  externo; con `stream:true` los resultados intermedios llegan en vivo
  (`response.output_text.delta`, cierre en `response.completed`).

## USO

```
py "%USERPROFILE%\.config\opencode\skills\qwen-mcp\scripts\consultar_mcp.py" --server-url "https://mcp.api-inference.modelscope.net/XXX/sse" --prompt "https://news.aibase.com/news, que noticias hay hoy" --json
py ...consultar_mcp.py --server-url URL --label fetch --description "scrapea URLs" --headers "Authorization=Bearer Tok3n" --stream
```

Flags: `--server-url` (obligatorio; sin el → exit 2 sin HTTP), `--prompt` (obligatorio),
`--label` (default `mcp-1`), `--description`, `--headers "K=V,K2=V2"` (los valores se
sanean de toda salida — nunca se imprimen), `--model` (default `qwen3.8-flash`; con
`--model qwen3.8-max` para maxima calidad), `--stream`, `--timeout` (default 180),
`--json`, `--out` (dentro del proyecto), `--base-url`. Salida `--json`:
`ok, model, endpoint, server_label, request_id, answer, mcp_calls[] (mcp_call/
mcp_list_tools: name/server_label/arguments/output), usage, seconds`.

Exit codes: `0` OK · `1` API/red (tras agotar cadena y reintentos 429) · `2`
configuracion (falta `--server-url` o `--prompt`, URL no http(s), `--headers` sin `=`,
falta key).

## MODELOS SOPORTADOS (doc oficial — via Responses API SOLO)

Series Qwen-Max 3.8/3.7 · Qwen-Plus 3.7/3.6/3.5 · Qwen-Flash 3.8/3.7/3.6/3.5 ·
Qwen3.8 open-source · Qwen3.6 open-source (excepto qwen3.6-27b) · Qwen3.5 open-source.
Recuerda: **bajo Token Plan solo la allowlist exact-string** (`qwen3.8-max`,
`qwen3.8-flash`, `qwen3.7-max`, `qwen3.7-plus`, `qwen3.6-flash`, ...) — y encima MCP se
silencia con `sk-sp-` (TRAMPA 200, ver CAUCION arriba).

## BILLING

Dos cargos: **tokens de inferencia del modelo** (Credits bajo Token Plan, USD bajo PAYG;
los schemas/nombres de las herramientas del server entran en el contexto = input tokens,
el ejemplo de la doc consumio ~20k de input) + **fees del proveedor del server MCP**
(reglas propias de cada plataforma, p. ej. ModelScope). Reportar `usage` SIEMPRE.

## KEY Y BASES — resolucion automatica. Nunca imprimir la key ni los headers

(stdout, stderr ni `--out`). Sin ninguna key → exit 2 con instruccion (crear key en
https://home.qwencloud.com/api-keys).

**Familia A — Responses API**, precedencia:

1. `~/.local/share/opencode/auth.json` → providers `alibaba-token-plan` /
   `alibaba-token-plan-cn` (key `sk-sp-*`) → **cadena de bases** probada en orden hasta
   responder en `/responses` sin 401/404/405 (el JSON registra cual funciono en `endpoint`):
   1. `https://token-plan.maas.qwencloudapi.com/compatible-mode/v1` (Token Plan OFICIAL
   documentada — las bases TP no llevan region ID — PRIMERA en la cadena; **200 verificada en
   vivo 2026-11-09** (evidencia `.tmp\qwen-split\tests\`; 7/7 llamadas ganaron esta base)) ·
   2. `https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1` (**LEGACY:
   funcionaba el 2026-10-07 — fallback, no necesaria desde 2026-11-09**) ·
   3. `https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1` (otros workspaces).
2. `ANTHROPIC_AUTH_TOKEN` si empieza por `sk-sp-` → misma cadena. 3. `DASHSCOPE_API_KEY`:
`sk-sp-*` → misma cadena; `sk-*` (pay-as-you-go) →
`https://maas.qwencloudapi.com/compatible-mode/v1`. 4. `--base-url` manda sobre todo (solo
esa base).

**Allowlist Token Plan** (`sk-sp-*`): cualquier otro modelo → `Model not exist`. Consumo
en **Credits**; los USD son referencia (pueden cambiar). Key `sk-sp-*` orientada a uso
interactivo; lotes/produccion → pay-as-you-go — y para MCP es **OBLIGATORIA** (TRAMPA 200,
CAUCION).

## ERRORES

| Situacion | Accion |
|---|---|
| Exit 2 `falta_server_url` | el usuario no dio endpoint SSE: pedirselo, NO improvisar |
| HTTP 401/403 del server MCP al conectar | token de la plataforma mal puesto en `--headers` (o caducado) — revisar en la pagina del server |
| `Model not exist` / tool rechazada con sk-sp- | MCP NO esta en la allowlist harness TP → key pay-as-you-go (ver CAUCION) |
| **HTTP 200 pero respuesta sin `mcp_calls` y tokens de input bajisimos** | **MCP ignorado silenciosamente bajo Token Plan (`sk-sp-`) = TRAMPA 200** → no insistir: key pay-as-you-go (ver CAUCION); el 200 no prueba que funciono |
| HTTP 400 en `tools` | recuerda: solo Responses, solo `server_protocol:"sse"`, <=10 servers |
| HTTP 429 | reintento automatico 2x (espera 10 s); persiste → reducir ritmo |
| Cuelga/timeout | el server externo tarda: `--stream` para ver progreso y subir `--timeout` |
| Respuesta sin usar herramientas | `server_description` vaga o pregunta sin relacion con el server: describir capacidades y reformular |

Detalle de bodies y ejemplo completo: `references\api-mcp.md`.

## ARCHIVOS

```
qwen-mcp/
├── SKILL.md
├── README.md
├── scripts/
│   └── consultar_mcp.py       # Responses API + tool type:mcp (SSE) — solo-stdlib
└── references/
    └── api-mcp.md             # bodies literales (sync y stream), ModelScope, errores
```
