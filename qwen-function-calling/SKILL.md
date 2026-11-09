---
name: qwen-function-calling
description: >
  Function calling (tools client-side) con modelos QwenCloud: el modelo pide llamar
  funciones que TU ejecutas y le devuelves el resultado — loop multi-turno completo
  documentado para Chat Completions (tool_calls anidados), Responses API (items flat
  function_call/function_call_output con call_id) y las trampas reales del terreno:
  tool_choice "required" NO lo soporta Qwen, thinking solo auto/none, forzar una tool
  exige enable_thinking:false, parallel_tool_calls default true (kimi-k3 lo ignora),
  en streaming hay que agregar los deltas de arguments por index, GLM exige
  tool_stream:true, Omni stream+modalities ["text"], realtime WS documental. Plantilla
  ejecutable scripts\plantilla_function_calling.py (loop clima SIMULADO end-to-end con
  key/base del Token Plan resuelta sola). Usar cuando el usuario pida conectar un modelo
  a funciones/APIs/BD propias con Qwen. NO para: tools del HARNESS del proveedor
  (busqueda/sandbox/pdf/mcp) → qwen-web-search, qwen-code-interpreter, qwen-pdf,
  qwen-mcp.
license: MIT
metadata:
  version: "3.0"
  split-de: "qwen-tools v2.0"
  api_base_responses: "https://token-plan.maas.qwencloudapi.com/compatible-mode/v1"
---

# QWEN-FUNCTION-CALLING — Herramientas client-side (loop modelo ↔ tu codigo)

El modelo no accede a datos en tiempo real ni sistemas externos por si solo: tu defines
tools (JSON Schema), el modelo DECIDE cuando llamarlas devolviendo una instruccion
(nombre + argumentos JSON), tu aplicacion las EJECUTA, inyectas el output en el historial
y el modelo sintetiza la respuesta final. Function calling NO es una tool del harness:
**todos los modelos de texto del Token Plan lo soportan** (tambien los de terceros:
DeepSeek, Kimi, GLM, MiniMax) — se pagan solo tokens.

## EL LOOP (5 pasos)

1. Envias pregunta + lista de `tools`.
2. El modelo responde con `tool_calls` (o texto directo si no necesita nada).
3. Tu ejecutas la funcion indicada (cada tool_call, TODOS).
4. Anades al historial un mensaje con el resultado (`role:"tool"` / item
   `function_call_output`) y vuelves a llamar.
5. El modelo combina resultado + pregunta → respuesta natural.

Plantilla ejecutable con el loop completo (clima SIMULADO, adaptarla a tus tools reales):

```
py "%USERPROFILE%\.config\opencode\skills\qwen-function-calling\scripts\plantilla_function_calling.py"
py ...plantilla_function_calling.py --prompt "clima en Tokyo" --json --out .tmp\fc_demo.json
py ...plantilla_function_calling.py --no-parallel
```

Flags: `--prompt`, `--model` (default `qwen3.8-flash`), `--max-turns` (tope del loop,
default 5), `--no-parallel`, `--timeout`, `--json`, `--out`, `--base-url`. Salida: traza
de cada decision/resultado + respuesta final (o JSON unico con `steps`). Exit codes:
`0` OK · `1` API/red (o loop sin respuesta final) · `2` configuracion.

## ESQUEMA DE LA TOOL — Chat Completions vs Responses (¡distintos!)

**Chat Completions** (`/chat/completions`) — envoltorio `function` ANIDADO:

```json
{"type": "function", "function": {"name": "get_current_weather",
  "description": "Util para comprobar el clima de una ciudad.",
  "parameters": {"type": "object", "properties": {"location": {"type": "string"}},
                 "required": ["location"]}}}
```

Respuesta: `choices[0].message.tool_calls[]` con `{id, type:"function",
function:{name, arguments(cadena JSON)}}`; el resultado se devuelve como
`{"role":"tool","tool_call_id":<id>,"content":<resultado>}`.

**Responses API** (`/responses`) — esquema **FLAT** (`name`/`parameters` top-level, SIN
wrapper `function`):

```json
{"type": "function", "name": "get_current_weather", "description": "...",
 "parameters": {"type": "object", "properties": {"location": {"type": "string"}},
                "required": ["location"]}}
```

La peticion trae en `output[]` un item `{"type":"function_call","id":"fc_…",
"call_id":"call_…","name":"…","arguments":"{...}"}`; se responde con item
`{"type":"function_call_output","call_id":<el call_id>,"output":<resultado>}`
(reenviando el item `function_call` en el input para conservar el contexto). El output
puede ser string o array de contenido (`input_text` + `input_image`: una URL de imagen
como string plano NO se parsea como imagen).

## tool_choice — las 4 reglas que rompen demos

- Default `"auto"` (el modelo decide). `"none"` (o no mandar tools) bloquea herramientas.
- Forzar UNA tool: `tool_choice={"type":"function","function":{"name":"..."}}`.
- **`"required"` NO lo soportan los modelos Qwen**: en modo thinking no esta soportado y
  en modo no-thinking no garantiza llamada (funciona en kimi/kimi-k3, no en qwen).
- Los modelos tipo `qwen3.8-max` traen thinking ON por defecto y **thinking solo acepta
  tool_choice "auto"/"none"**: para forzar una herramienta hay que APAGAR thinking —
  Chat: `extra_body={"enable_thinking": False}`; Responses: `enable_thinking` esta
  **deprecated**, se razona con `reasoning.effort`.
- Al resumir los outputs de herramientas (segunda llamada), **QUITAR `tool_choice`** —
  si no, la API vuelve a devolver tool calls en vez de texto.

## parallel_tool_calls

- Default `true`: con "¿que tiempo hace en Beijing y Shanghai?" el modelo puede devolver
  VARIOS `tool_calls` en un turno (procesarlos en paralelo solo si son independientes;
  con dependencia, loop serial).
- **kimi-k3 IGNORA `parallel_tool_calls:false`**: puede devolver varios tool_calls igual
  → el loop SIEMPRE debe iterar sobre todos los recibidos (la plantilla lo hace).
- Pensar en la suma: multiple tool calls = multiples ejecuciones y multiples vueltas al
  modelo → mas tokens.

## Streaming con function calling

Los tool_calls llegan TROCEADOS: el `name` en el primer chunk y los `arguments` en
deltas incrementales **agrupables por `index`** — hay que concatenar los deltas antes de
parsear JSON y, al reconstruir el mensaje assistant, sustituir `tool_calls` por el
 agregado:

```python
tool_calls = {}
for chunk in stream:
    d = chunk.choices[0].delta.tool_calls
    if d:
        for tc in d:
            i = tc.index
            tc.function.arguments = tc.function.arguments or ""
            if i not in tool_calls:
                tool_calls[i] = tc
            else:
                tool_calls[i].function.arguments += tc.function.arguments
```

## Particularidades por modelo/familia (doc oficial 2026-11-09)

- **GLM**: hay que mandar `tool_stream:true` (SDK: `extra_body={"tool_stream": True}`) o
  el modelo NO devuelve `tool_calls` — en `glm-5.3` ya es default true.
- **Qwen-Omni (no realtime)** en la fase de seleccion de tool: **exige `stream=True`** y
  se recomienda `modalities=["text"]` (evita audio innecesario).
- **Thinking**: con `enable_thinking:true` el modelo emite `reasoning_content` antes de
  los tool_calls y ese campo **debe reenviarse** en las llamadas siguientes del loop.
- **Realtime (WS) — SECCION DOCUMENTAL, sin script en esta skill**:
  `qwen3.8-omni-flash-realtime`, `qwen3.5-omni-plus-realtime`,
  `qwen3.5-omni-flash-realtime` soportan function calling por WebSocket (y la serie
  Qwen-Audio-Realtime 3.0/3.1). Flujo: conectar `wss://{host}/api-ws/v1/realtime`, meter
  las tools en `session.update`; el server emite `response.function_call_arguments.done`
  (con `name`/`arguments`/`call_id`); el cliente ejecuta localmente, manda
  `conversation.item.create` con item `{"type":"function_call_output","call_id":...,
  "output":...}` y dispara `response.create` para la respuesta final (audio+texto). La
  serie Omni-Realtime **no soporta `tool_choice` ni `parallel_tool_calls`**. No
  implementar aqui: requiere gestion de audio en vivo (ver la guia realtime de la doc).

## Best practices (doc oficial)

- **<=20 tools** en el request; bibliotecas grandes → capa de ruteo (busqueda semantica,
  filtro por keywords o un LLM router barato) antes de pasarlas al modelo.
- **Least privilege**: tools default read-only; jamas dar acceso directo a operaciones
  peligrosas (ejecutar codigo, borrar archivos, transferencias).
- **Confirmacion humana en escrituras**: email, cambios de datos, acciones irreversibles =
  pedirla al usuario, no la disparen solas.
- **Timeouts por paso + fallback** claro ("no puedo consultar X ahora, reintenta").
- Descripciones especificas y evaluadas: si el modelo elige mal la tool o extrae mal los
  parametros, pulir `description`/system prompt ANTES de subir de modelo; montar un set
  de evaluacion con la vida real.
- Mostrar progreso en UI ("buscando el clima...").

## Billing

Los `description`/schemas de las tools viajan en el prompt y **cuentan como input
tokens** (mas tools = mas costo por turno) — otra razon para el filtro de <=20. Bajo
Token Plan todo se liquida en Credits (key `sk-sp-*` para uso interactivo; lotes →
pay-as-you-go). Function calling es EXCLUYENTE con la tool harness `code_interpreter`
(→ skill qwen-code-interpreter).

## KEY Y BASES — resolucion automatica. Nunca imprimir la key ni el body

(stdout, stderr ni `--out`). Sin ninguna key → exit 2 con instruccion (crear key en
https://home.qwencloud.com/api-keys). La plantilla usa **Familia A** (mismos hosts para
`/chat/completions`):

1. `~/.local/share/opencode/auth.json` → providers `alibaba-token-plan` /
   `alibaba-token-plan-cn` (key `sk-sp-*`) → cadena de bases en orden: 1.
   `https://token-plan.maas.qwencloudapi.com/compatible-mode/v1` (Token Plan OFICIAL
   documentada — sin region ID — PRIMERA, R0 2026-11-09; **200 verificada en vivo 2026-11-09**,
   evidencia `.tmp\qwen-split\tests\` — 7/7 llamadas ganaron esta base), 2.
   `https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1` (**LEGACY —
   fallback, no necesaria desde 2026-11-09**), 3. `https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`.
2. `ANTHROPIC_AUTH_TOKEN` si empieza por `sk-sp-` → misma cadena. 3. `DASHSCOPE_API_KEY`:
`sk-sp-*` → cadena TP; `sk-*` (pay-as-you-go) → `https://maas.qwencloudapi.com/compatible-mode/v1`
(region SG oficial: `https://ap-southeast-1.maas.qwencloudapi.com/compatible-mode/v1`).
4. `--base-url` manda sobre todo (solo esa base).

**Allowlist Token Plan** (`sk-sp-*`): todos los de texto la soportan; cualquier modelo
ajeno → `Model not exist`.

## ERRORES

| Situacion | Accion |
|---|---|
| El modelo nunca llama la tool | `description` vaga o pregunta ajena a las tools: pulirlas; `tool_choice` forzado (recordar enable_thinking:false en qwen) |
| Pides `tool_choice:"required"` a un qwen | NO soportado (solo auto/none o forzar una + thinking off); kimi si lo acepta |
| GLM no devuelve tool_calls | falta `tool_stream:true` (glm-5.3 ya default true) |
| `json.loads` revienta los arguments | en streaming NO agregar deltas por `index` antes de parsear |
| tool_choice presente en la 2a llamada | QUITARLO al resumir outputs, si no devuelve tool_calls otra vez |
| Dos calls en un turno con parallel_tool_calls:false | kimi-k3 lo ignora — iterar SIEMPRE todos los tool_calls |
| HTTP 401 / `Model not exist` / 429 | key↔host, allowlist TP, rate limit (reintentos 2x10 s en la plantilla) |
| Omni sin tool_calls | falta `stream=True` (+ `modalities:["text"]`) |

Detalle de bodies literales y ejemplos completos: `references\api-function-calling.md`.

## ARCHIVOS

```
qwen-function-calling/
├── SKILL.md
├── README.md
├── scripts/
│   └── plantilla_function_calling.py  # loop clima SIMULADO end-to-end (demo/plantilla)
└── references/
    └── api-function-calling.md        # bodies Chat/Responses/stream/Omni/realtime
```
