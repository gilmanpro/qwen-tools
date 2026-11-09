---
name: qwen-code-interpreter
description: >
  Corre Python en el sandbox REMOTO de QwenCloud (Responses API, tool
  {type:"code_interpreter"}, key sk-sp- del Token Plan resuelta sola desde auth.json):
  calculo pesado, cifrados/hashes/encodings con datos PROPIOS, analisis express de
  CSV/JSON sin instalar paquetes, prototipar un algoritmo. USO EXCLUSIVO @5-dev,
  max 1-2 llamadas por tarea — cualquier otro agente NO la activa. Temporalmente
  gratis (solo tokens), EXCLUYENTE con function calling. Activar SOLO cuando el usuario
  lo pida explicitamente o ninguna via gratuita (bash local) lo cubra. NO para: codigo
  que corre en el bash local (gratis y ve tus archivos), cambios al repo, secretos o
  datos de terceros en el prompt (PROHIBIDO — viaja a un servidor externo), busqueda
  web → qwen-web-search.
license: MIT
metadata:
  version: "3.0"
  split-de: "qwen-tools v2.0"
  api_base_responses: "https://token-plan.maas.qwencloudapi.com/compatible-mode/v1"
---

# QWEN-CODE-INTERPRETER — Python en el sandbox remoto de QwenCloud (SOLO @5-dev)

El modelo escribe Python, lo ejecuta en un sandbox REMOTO de QwenCloud y devuelve los
logs + su respuesta final (Responses API, tool `code_interpreter`, default
`qwen3.8-flash`; smoke test real 2026-10-07: HTTP 200, ~21 s). Un `scripts\ejecutar_codigo.py`
solo-stdlib hace todo: POST `/responses`, recorrido de items, cadena de bases, contrato JSON.

## POLITICA DE ACTIVACION (leer primero)

- **Uso EXCLUSIVO del agente @5-dev** y solo en casos especiales: ciberseguridad con
  datos PROPIOS (hashes, cifrados, encodings), calculos numericos/estadisticos pesados,
  analisis express de datos (CSV/JSON) sin instalar paquetes, prototipar/verificar un
  algoritmo puntual.
- **Max 1-2 llamadas por tarea** (cada invocacion exitosa descuenta Credits y sube
  tokens); `--model qwen3.8-max` solo con autorizacion explicita.
- El sandbox es **EFIMERO**: no hay persistencia entre llamadas, arranca de cero.
- **NO activar** para: codigo que corre en el bash local (gratis, mas rapido, ve los
  archivos reales), cambios al repo o archivos locales (el sandbox NUNCA toca tu disco),
  **secretos, claves, tokens o datos personales de terceros en el prompt (PROHIBIDO —
  viaja a un servidor externo; jamas)**, scrapear una URL concreta → leer la URL con el
  arnes (curl/webfetch), busqueda web → skill `qwen-web-search`.
- Redacta el prompt **pidiendo explicitamente el interprete** y con **codigo stdlib**:
  el sandbox no documenta red ni paquetes extra (`requests`/`pandas` puede fallar —
  verlo en `calls[].logs`).

## COMO FUNCIONA (doc oficial 2026-11-09)

El modelo procesa cada request en etapas: 1) thinking, 2) ejecucion de codigo en el
sandbox, 3) integracion del resultado, 4) respuesta natural. Los pasos 2-3 **pueden
repetirse varias veces dentro de un mismo request** (varias llamadas al interprete; el
`usage` agrega los tokens de todas las inferencias).

Limitaciones documentadas:

- **EXCLUYENTE con function calling**: `code_interpreter` y tools `function` NO se
  activan a la vez — habilitar ambas devuelve error. El script manda UNA sola tool (la
  skill `qwen-function-calling` documenta el lado excluyente).
- **Chat Completions y DashScope EXIGEN `stream:true`** (sin stream devuelven error).
  La **Responses API NO tiene esa limitacion** — por eso el script usa `/responses` sin stream.
  Con key Token Plan (`sk-sp-`) usa SIEMPRE Responses: con Chat Completions las tools del
  harness NO se invocan.
- Un request dispara multiples inferencias: el contador real de ejecuciones esta en
  `usage` (abajo), no en el numero de llamadas HTTP.

## USO

```
py "%USERPROFILE%\.config\opencode\skills\qwen-code-interpreter\scripts\ejecutar_codigo.py" --prompt "Usa el interprete de codigo para calcular factorial(20) y los primos menores de 50"
py "%USERPROFILE%\.config\opencode\skills\qwen-code-interpreter\scripts\ejecutar_codigo.py" --prompt-file caso.txt --json
py "%USERPROFILE%\.config\opencode\skills\qwen-code-interpreter\scripts\ejecutar_codigo.py" --prompt "..." --out .tmp\respuesta_ci.json --timeout 180 --model qwen3.8-flash
```

Flags: `--prompt` / `--prompt-file` (excluyentes, uno obligatorio), `--model` (default
`qwen3.8-flash`), `--timeout` (default 180 s), `--json`, `--out` (ruta DENTRO del
proyecto, nunca fuera), `--base-url` (salta la cadena). Exit codes: `0` OK · `1` API/red
(tras agotar cadena y reintentos 429: 2 × espera 10 s) · `2` configuracion (falta key,
prompt vacio, flag invalido).

Salida con `--json` (UN unico JSON en stdout; diagnosticos por stderr): `output_text`,
`calls[]` (`code`/`logs`/`status`), `ejecuciones`, `request_id`, `usage`
(input/output/total tokens), `latencia_s`, `endpoint`. Items leidos de
`output[].type=="code_interpreter_call"`. `calls[].status != "completed"` = el sandbox
fallore → reenviar tal cual y reescribir el prompt en stdlib. Reportar SIEMPRE
`ejecuciones` + `request_id` + tokens (trazabilidad de Credits).

Conteo de ejecuciones facturado: `usage.x_tools.code_interpreter.count`; fallback suma
de `usage.x_details[].plugins.code_interpreter.count` (NO existe `usage.plugins`
top-level en Responses — verificado 2026-10-07). En la via **DashScope** el count vive en
`usage.plugins.code_interpreter.count` y el **codigo ejecutado** se recupera del campo
`tool_info` de cada chunk de stream:

```json
"tool_info": [ { "code_interpreter": {"code": "123**21"}, "type": "code_interpreter" } ]
```

(Se acumula entre llamadas del mismo request; `usage.plugins` da el total. La via Chat
Completions NO devuelve el codigo ejecutado: si necesitas inspeccionarlo, usa Responses
o DashScope.)

## MODELOS SOPORTADOS (doc oficial 2026-11-09)

- **Responses API (recomendados)**: Qwen3.8-Max series, Qwen3.7-Max series,
  `qwen3.8-flash`, Qwen3.7/3.6/3.5-Plus series; DeepSeek `deepseek-v4.1-flash`,
  `deepseek-v4.1-flash-1017`, `deepseek-v4-pro-0813`, `deepseek-v4-flash-0731`,
  `deepseek-v4-pro`; GLM `glm-5.2`; Qwen3.8 open-source series.
- Tambien en Responses (rendimiento menor): Qwen3.7/3.6/3.5-Flash series, Qwen3.6
  open-source (menos qwen3.6-27b), Qwen3.5 open-source.
- `deepseek-v4.1-flash-1017` y `kimi-k3.1-pro` (deployado en QwenCloud) soportan la tool
  `code_interpreter` en Responses API en TODAS las regiones (Singapur, Beijing-N2,
  Frankfurt, Hong Kong, Tokio, Virginia).
- **Chat Completions / DashScope**: Qwen3.7-Max series (modo thinking), Qwen3.5-Plus —
  siempre con `stream:true` (con key `sk-sp-` elige Responses en su lugar).
- **Allowlist Token Plan (`sk-sp-`)**: cualquier otro modelo → `Model not exist`.

## KEY Y BASES — resolucion automatica. Nunca imprimir la key ni el body

(stdout, stderr ni `--out`). Sin ninguna key → exit 2 con instruccion (crear key en
https://home.qwencloud.com/api-keys).

**Familia A — Responses API**, precedencia:

1. `~/.local/share/opencode/auth.json` → providers `alibaba-token-plan` /
   `alibaba-token-plan-cn` (key `sk-sp-*`) → **cadena de bases** probada en orden hasta
   responder en `/responses` sin 401/404/405 (el JSON registra cual funciono en
   `endpoint`):

| Base candidata | Estado |
|---|---|
| `https://token-plan.maas.qwencloudapi.com/compatible-mode/v1` | **Token Plan OFICIAL documentada** (las bases TP no llevan region ID) — PRIMERA (R0 2026-11-09); **200 verificada en vivo 2026-11-09** (evidencia `.tmp\qwen-split\tests\`; 7/7 llamadas ganaron esta base) |
| `https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1` | LEGACY: 200 verificado 2026-10-07 (no aparece en doc) — **fallback, no necesaria desde 2026-11-09** |
| `https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1` | 401 con la key sk-sp- actual (otros workspaces) |

(Retirada de la cadena: `https://ws-<ID-workspace>.ap-southeast-1.maas.aliyuncs.com/api/v1`
— RETIRADA, 404 permanente, nunca en cadena, sin respaldo documental. Mismo patron que
`buscar_web.py` de qwen-web-search.)

2. `ANTHROPIC_AUTH_TOKEN` si empieza por `sk-sp-` → misma cadena. 3. `DASHSCOPE_API_KEY`:
`sk-sp-*` → misma cadena; `sk-*` (pay-as-you-go) →
`https://maas.qwencloudapi.com/compatible-mode/v1`. 4. `--base-url` manda sobre todo
(solo esa base).

**Permitido para la allowlist y verificado con code_interpreter (2026-10-07)**: consumo
en **Credits**; la tool esta **temporalmente gratis** (solo paga los tokens), que suben
por las multiples inferencias del loop interno. Key `sk-sp-*` orientada a uso
interactivo; lotes/produccion → key pay-as-you-go con saldo.

## ERRORES

| Situacion | Accion |
|---|---|
| HTTP 429 | el script reintenta solo 2 veces (espera 10 s); persiste → reducir ritmo (TP: esperar 1 min) |
| HTTP 401 / `InvalidApiKey` | key invalida o key↔host incorrectos (`sk-sp-*` ⇒ host token-plan). Detenerse |
| `Model not exist` | modelo fuera de la allowlist del Token Plan |
| HTTP 400 por mezclar `code_interpreter` + `function` tools | son EXCLUYENTES: una sola tool por request |
| HTTP 400 sin stream en Chat Completions/DashScope | la tool exige `stream:true` en esas vias; usa Responses |
| `calls[].status != "completed"` | fallo del sandbox (timeout/import de paquete inexistente) → reescribir en stdlib y reintentar UNA vez maximo |
| Timeout general | calculo/serializacion muy pesado → dividir en partes mas pequenas |
| Salida de error JSON | `{"ok":false,"error":{"tipo","http_status","mensaje"},"attempted":[bases]}` — reenviar literal, NO inventar |

Exit codes: `0` OK · `1` API/red tras agotar cadena · `2` configuracion/uso (falta key o
prompt, flag invalido).

## ARCHIVOS

```
qwen-code-interpreter/
├── SKILL.md                    # este archivo (el detalle API vive aqui)
├── README.md
└── scripts/
    └── ejecutar_codigo.py      # Responses API + tool code_interpreter (solo-stdlib)
```
