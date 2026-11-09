# api-mcp.md — Conectar servidores MCP (Responses API) — detalle API

Fuente: docs.qwencloud.com/developer-guides/tool-calling/mcp (fetcheado 2026-11-09).
Leer SOLO cuando el body de SKILL.md no baste.

## Alcance

- Via: **Responses API** (`POST {base}/responses`) — MCP NO existe en Chat Completions.
- Protocolo con el server: **`server_protocol:"sse"` (UNICO soportado)**.
- **Maximo 10 servers MCP por request** (10 entradas `type:"mcp"` en `tools`).

## Body literal — no-stream (de la doc oficial, adaptado a raw JSON)

```json
{
  "model": "qwen3.8-max",
  "input": "https://news.aibase.com/news, what is the AI news today?",
  "tools": [
    {
      "type": "mcp",
      "server_protocol": "sse",
      "server_label": "fetch",
      "server_description": "Fetch MCP Server that provides web scraping capabilities. It can scrape the content of a specified URL and return it as text.",
      "server_url": "https://mcp.api-inference.modelscope.net/xxx/sse"
    }
  ]
}
```

curl equivalente (region Singapore PAYG; sustituir la base por la cadena TP de SKILL.md
si usas `sk-sp-` — recordando que con `sk-sp-` la tool se ACEPTA (200) pero se SILENCIA: TRAMPA 200, no sirve para MCP real):

```bash
curl -X POST "https://ap-southeast-1.maas.qwencloudapi.com/compatible-mode/v1/responses" \
  -H "Authorization: Bearer $DASHSCOPE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{ "model": "qwen3.8-max",
        "input": "https://news.aibase.com/news, que noticias hay hoy?",
        "tools": [{ "type": "mcp", "server_protocol": "sse", "server_label": "fetch",
                    "server_description": "Fetch MCP Server: scrapea una URL y devuelve texto",
                    "server_url": "https://mcp.api-inference.modelscope.net/xxx/sse",
                    "headers": { "Authorization": "Bearer <token-modelscope>" } }] }'
```

SDK (lo que representa el body de arriba):

```python
from openai import OpenAI
client = OpenAI(api_key=os.getenv("DASHSCOPE_API_KEY"),
                base_url="https://ap-southeast-1.maas.qwencloudapi.com/compatible-mode/v1")
mcp_tool = {
  "type": "mcp",
  "server_protocol": "sse",
  "server_label": "fetch",
  "server_description": "Fetch MCP Server that provides web scraping capabilities. It can scrape the content of a specified URL and return it as text.",
  "server_url": "https://mcp.api-inference.modelscope.net/xxx/sse",  # tu endpoint SSE
}
response = client.responses.create(model="qwen3.8-max",
                                   input="https://news.aibase.com/news, what is the AI news today?",
                                   tools=[mcp_tool])
print(response.output_text)
```

## Respuesta de ejemplo (doc oficial)

El server del ejemplo ("Fetch") devolvio texto coherente con scraping + respuesta larga:

```
[Model Response]
Based on the documentation for the Model Context Protocol (MCP) ... 
[Token Usage] Input: 20583, Output: 1638, Total: 22221
```

Nota el input tokens (~20k): la lista de herramientas del server entra en el contexto →
**los servers con muchas herramientas inflan los tokens de input**. Items de `output[]`
que interesan: `mcp_list_tools` (herramientas descubiertas), `mcp_call` (`name`,
`arguments`, `output`, `server_label`) y el `message` final.

## Body literal — stream

`{"model":..., "input":..., "tools":[...], "stream": true}`. Eventos SSE relevantes:

```python
stream = client.responses.create(model="qwen3.8-max", input="...", tools=[mcp_tool], stream=True)
for event in stream:
    if event.type == "response.content_part.added":   # empieza la respuesta
        ...
    elif event.type == "response.output_text.delta":   # texto en vivo
        print(event.delta, end="", flush=True)
    elif event.type == "response.completed":           # fin: event.response.usage
        ...
```

Recomendado: las llamadas MCP son multi-interaccion (lista tools → N llamadas al server →
sintesis); sin stream se espera todo el ciclo a ciegas.

## Parametros de la tool

| Parametro | Requerido | Descripcion |
|---|---|---|
| `type` | SI | `"mcp"` |
| `server_protocol` | SI | SOLO `"sse"` |
| `server_label` | SI | nombre identificador del server |
| `server_description` | NO (recomendado) | capacidades del server; mejora la eleccion de herramienta |
| `server_url` | SI | endpoint SSE del server (lo da la plataforma: ModelScope "Service configuration") |
| `headers` | NO | cabeceras al conectar (p. ej. `Authorization` con el token de la plataforma) |

## Modelos soportados (doc oficial; SOLO Responses API)

- Qwen-Max: series 3.8, 3.7
- Qwen-Plus: series 3.7, 3.6, 3.5
- Qwen-Flash: 3.8, 3.7, 3.6, 3.5
- Qwen3.8 open-source; Qwen3.6 open-source (excluye qwen3.6-27b); Qwen3.5 open-source

Bajo Token Plan (`sk-sp-`) aplica la allowlist exact-string Y la **CAUCION F2b-3**: la tool
`mcp` es **aceptada (200) pero silenciada** (`mcp_calls:[]`, input ~109 tok; las tools del
server nunca se inyectan) → **TRAMPA 200**, para MCP real hace falta key pay-as-you-go.
Evidencia: `.tmp\qwen-split\tests\qwen-mcp\consultar_mcp.json` (endpoint `amap-maps`).

## Billing

1. **Inferencia del modelo**: por tokens (Credits bajo TP; USD bajo PAYG). El listado de
   tools del server cuenta como input.
2. **Fee del server MCP**: reglas del proveedor de cada server (ModelScope, etc.) —
   ajenas a QwenCloud.

## Donde sacar el endpoint SSE (ejemplo ModelScope, doc oficial)

1. Abrir el server deseado (p. ej. `https://modelscope.ai/mcp/servers/@modelcontextprotocol/fetch`).
2. Seccion **Service configuration** (derecha): copia el **SSE Endpoint** → `server_url`.
3. Copia el token/credencial que exponga → `headers` (tipicamente `Authorization`).
4. NO inventar URLs: si el usuario no tiene server, explicarle este paso.

## Errores

- 401/403 del server: token de `headers` invalido/caducado (revisar plataforma).
- 400 en `tools`: no es Responses, `server_protocol` != "sse", >10 servers, o `server_url`
  inaccesible desde la plataforma (debe ser publica).
- `Model not exist` con `sk-sp-`: modelo fuera de allowlist TP.
- **200 sin `mcp_calls` y input bajisimo con `sk-sp-`**: MCP ignorado silenciosamente
  (TRAMPA 200) — no insistir; usar PAYG. No confundir con exito real.
- Rechazo de la tool `mcp` con `sk-sp-`: esperado — usar PAYG.
- Generales: docs.qwencloud.com/api-reference/preparation/error-messages.
