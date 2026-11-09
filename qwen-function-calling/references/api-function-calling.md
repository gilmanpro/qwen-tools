# api-function-calling.md — Function calling en QwenCloud (detalle API)

Fuente: docs.qwencloud.com/developer-guides/tool-calling/function-calling (fetcheado
2026-11-09). Leer SOLO cuando lo de SKILL.md no baste. Bases de los ejemplos: region
Singapore PAYG (`https://ap-southeast-1.maas.qwencloudapi.com/compatible-mode/v1`, keys
region-specific); con `sk-sp-` usar la cadena TP de SKILL.md (oficial primero).

## Modelos que lo soportan (doc oficial)

- TODOS los modelos generales de generacion de texto (incluidos terceros: DeepSeek,
  Kimi, GLM, MiniMax) y la serie open-source Qwen3.8 (`qwen3.8-2.4t-a95b`).
- Vision: Qwen3-VL, `qwen3.8-omni-flash`, `qwen3.5-omni-plus`, `qwen3.5-omni-flash`,
  `qwen3-omni-flash`.
- Realtime (WS): `qwen3.8-omni-flash-realtime`, `qwen3.5-omni-plus-realtime`,
  `qwen3.5-omni-flash-realtime`; voz: serie Qwen-Audio-Realtime (3.1/3.0 Plus y Flash).
- GLM: exige `tool_stream:true` (SDK: `extra_body={"tool_stream": True}`); en glm-5.3 es
  default true. Sin el campo, no devuelve tool_calls.

## 1. Chat Completions — loop completo (ejemplo oficial "Getting started")

Esquema de tool (wrapper `function` ANIDADO):

```json
{
  "type": "function",
  "function": {
    "name": "get_current_weather",
    "description": "Useful when you want to check the weather for a specific city.",
    "parameters": {
      "type": "object",
      "properties": {
        "location": {"type": "string", "description": "City or county, such as Singapore or New York."}
      },
      "required": ["location"]
    }
  }
}
```

`parameters` = JSON Schema de los inputs (omitirlo si la funcion no recibe nada). El
modelo usa `description` para elegir herramienta y extraer parametros: escribirlos
claros y especificos.

Loop (SDK; la plantilla lo implementa en raw HTTP):

```python
messages = [{"role": "user", "content": "What's the weather in Singapore?"}]
response = client.chat.completions.create(model="qwen3.8-max", messages=messages, tools=tools)
msg = response.choices[0].message
messages.append(msg)                      # content puede venir None → poner ""
while msg.tool_calls:
    for tc in msg.tool_calls:             # TODOS, no solo [0] (kimi-k3 trae varios)
        args = json.loads(tc.function.arguments)
        result = REGISTRO[tc.function.name](args)
        messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
    response = client.chat.completions.create(model="qwen3.8-max", messages=messages, tools=tools)
    msg = response.choices[0].message
    messages.append(msg)
print(msg.content)                        # respuesta final natural
```

Crudo del mensaje assistant con tool_calls (doc oficial):

```json
{"role": "assistant",
 "tool_calls": [
   {"function": {"name": "get_current_weather", "arguments": "{\"location\": \"Beijing\"}"},
    "index": 0, "id": "call_c2d8a3a2...", "type": "function"},
   {"function": {"name": "get_current_weather", "arguments": "{\"location\": \"Shanghai\"}"},
    "index": 1, "id": "call_dc7f2f67...", "type": "function"}
 ]}
```

## 2. tool_choice (doc oficial, literal)

```python
# Forzar UNA tool concreta (en qwen exige thinking OFF):
client.chat.completions.create(model="qwen3.8-max", messages=messages, tools=tools,
    tool_choice={"type": "function", "function": {"name": "get_current_weather"}},
    extra_body={"enable_thinking": False})
# "required": solo kimi-k3 y compania — LOS MODELOS Qwen NO lo soportan
#   (thinking: no soportado; no-thinking: no garantiza llamada).
client.chat.completions.create(model="kimi/kimi-k3", messages=messages, tools=tools,
    tool_choice="required")
# Bloquear tools:
client.chat.completions.create(model="qwen3.8-max", messages=messages, tools=tools,
    tool_choice="none")
```

- Con thinking ON, tool_choice solo admite `"auto"`/`"none"`.
- En la segunda vuelta (resumir tool outputs) **quitar `tool_choice`**, si no la API
  vuelve a devolver tool calls.

## 3. parallel_tool_calls

`parallel_tool_calls` default `true`; multiple llamadas independientes en un turno.
Dependencia entre tools → loop serial. **kimi-k3 ignora `false`**: puede devolver varios
tool_calls igualmente — iterar siempre todos.

## 4. Multi-turno (estructura de messages de la doc)

```
[system (estrategia), user (1a pregunta), assistant (tool call), tool (output),
 assistant (resumen), user (2a pregunta)]
```

Conservar el array entre rondas: sin el contexto anterior el modelo no sabe quiza que
herramienta usar.

## 5. Streaming — agregacion de arguments (codigo oficial)

```python
tool_calls = {}
for response_chunk in stream:
    delta_tool_calls = response_chunk.choices[0].delta.tool_calls
    if delta_tool_calls:
        for tc in delta_tool_calls:
            i = tc.index
            tc.function.arguments = tc.function.arguments or ""
            if i not in tool_calls:
                tool_calls[i] = tc
            else:
                tool_calls[i].function.arguments += tc.function.arguments
print(tool_calls[0].model_dump_json())
```

El nombre de la funcion llega en el PRIMER chunk; los arguments en deltas incremental
(agrupar por `index`, concatenar, parsear JSON al final). Al construir el mensaje
assistant de la segunda llamada, sustituir `tool_calls` por el agregado.

## 6. Thinking + function calling

`extra_body={"enable_thinking": True}, stream=True` → el modelo emite
`reasoning_content` (analisis de intencion/seleccion/parametros) antes de los tool_calls.
**Reenviar `reasoning_content`** en las llamadas subsecuentes del historial assistant.
En Responses API `enable_thinking` esta **deprecated**: usar `reasoning.effort`.

## 7. Responses API — items flat (3 pasos oficiales)

Paso 1, tools con esquema FLAT (`name`/`parameters` top-level, sin wrapper `function`):

```python
tools = [{"type": "function", "name": "get_current_weather",
          "description": "Useful when you want to check the weather for a specific city.",
          "parameters": {"type": "object",
                         "properties": {"location": {"type": "string"}},
                         "required": ["location"]}}]
response = client.responses.create(model="qwen3.8-max", tools=tools,
                                   input="What's the weather in Singapore?")
```

Paso 2, item recibido en `output[]`:

```json
{"type": "function_call", "id": "fc_12345", "call_id": "call_xxx",
 "name": "get_current_weather", "arguments": "{\"location\": \"Singapore\"}"}
```

Paso 3, devolver el resultado con `function_call_output` (matching por `call_id`,
reenviando el item function_call en el historial):

```python
response = client.responses.create(
    model="qwen3.8-max", tools=tools,
    input=[
        {"type": "message", "role": "user", "content": "What's the weather in Singapore?"},
        response.output[0],
        {"type": "function_call_output", "call_id": response.output[0].call_id,
         "output": tool_result},
    ])
print(response.output_text)
```

El output de la tool es usualmente string; para que el modelo ENTIENDA una imagen
producida por la tool, pasar array de contenido con items `{"type":"input_text","text":...}`
y `{"type":"input_image","image_url":...}` — **una URL de imagen como string plano se
trata como texto y NO se parsea como imagen** (ambas vias, Chat y Responses, aceptan
string o array).

## 8. Qwen-Omni (no realtime) — stream OBLIGATORIO en la fase de tools

```python
completion = client.chat.completions.create(
    model="qwen3-omni-flash",
    messages=[{"role": "user", "content": "What's the weather in Singapore?"}],
    modalities=["text"],      # recomendado: evita audio durante la seleccion
    stream=True,              # EXIGIDO para recuperar tool info
    tools=tools)
for chunk in completion:
    if chunk.choices:
        print(chunk.choices[0].delta.tool_calls)
```

Salida (doc oficial): deltas `[ChoiceDeltaToolCall(index=0, id='call_…',
function=…name='get_current_weather'…), (…arguments=' {"location": "Singapore"}'…), None]`
→ agregar como en seccion 5.

## 9. Realtime via WebSocket — DOCUMENTAL (sin script aqui)

Modelos: qwen3.8-omni-flash-realtime, qwen3.5-omni-plus-realtime,
qwen3.5-omni-flash-realtime (y serie Qwen-Audio-Realtime). WSS:
`wss://{region}.maas.qwencloudapi.com/api-ws/v1/realtime` (TP:
`wss://token-plan.maas.qwencloudapi.com/api-ws/v1/realtime?model=…`).

Flujo (doc oficial):
1. Conectar WS y pasar las definiciones de tools en `session.update`.
2. Fase 1: audio del usuario (`append_audio()`), VAD detecta fin de habla, el servidor
   decide la tool y emite:

```json
{"type": "response.function_call_arguments.done",
 "response_id": "resp_…", "item_id": "item_…", "output_index": 0,
 "name": "get_current_weather", "call_id": "call_…",
 "arguments": "{\"location\": \"Hangzhou\"}"}
```

3. El cliente ejecuta la funcion localmente. Fase 2: devuelve el resultado y dispara la
   respuesta final:

```json
{"type": "conversation.item.create",
 "item": {"type": "function_call_output", "call_id": "call_…",
          "output": "The weather in Hangzhou today is sunny, 25°C, light breeze."}}
```

   luego `response.create` → recibir `response.audio.delta` /
   `response.audio_transcript.delta`.
4. La serie Omni-Realtime **NO soporta `tool_choice` ni `parallel_tool_calls`**.
Implementacion de referencia: SDK DashScope `dashscope.audio.qwen_omni`
(OmniRealtimeConversation + callback `response.function_call_arguments.done` →
`create_item` + `create_response`) — guia en
/developer-guides/speech/realtime-multimodal-speech y eventos en
/api-reference/real-time-multimodal/{client-events,server-events}. MCP server-side con
flujo de aprobacion: /api-reference/real-time-multimodal/interaction-process#qwen38-mcp-flow.

## 10. Alternativa sin schema

Se puede embutir la info de herramientas en el system prompt (en lugar del parametro
`tools`) para modelos/compatibilidades antiguas — menos fiable: preferir el schema.

## 11. Billing (doc oficial)

Las descripciones de las tools cuentan como **input tokens** y se facturan con el prompt.
Nada de fees por herramienta en function calling (a diferencia de las harness tools).
Bajo Token Plan: todo en Credits.

## 12. Best practices (doc oficial, resumen)

Set de herramientas <=20 + capa de ruteo; least privilege (default read-only, nunca
ejecucion de codigo/borrado/transferencias directas); confirmacion humana para escrituras
irreversibles; timeouts independientes por paso y respuesta de fallback; evaluar
precision de seleccion/extraccion con dataset propio y pulir descripciones antes de
cambiar de modelo; progreso visible en UI.

Errores generales: /api-reference/preparation/error-messages.
