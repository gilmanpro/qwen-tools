# API Qwen-Audio (QwenCloud) — referencia completa

Fuentes (docs oficiales, consultar para cambios de version; fetch verificado 2026-11-09):

- https://docs.qwencloud.com/api-reference/speech-synthesis/cosyvoice/websocket-api — protocolo WS run/continue/finish-task, parametros, limites de texto, timeout 23 s
- https://docs.qwencloud.com/api-reference/speech-synthesis/qwen-audio-tts/http-api — **TTS HTTP one-shot** (request/response literales abajo)
- https://docs.qwencloud.com/token-plan/best-practices/speech-synthesis — **via HTTP documentada PARA TOKEN PLAN** (curl exacto abajo)
- https://docs.qwencloud.com/developer-guides/speech/tts-models — matriz modelo × WS/HTTP
- https://docs.qwencloud.com/developer-guides/speech/asr y https://docs.qwencloud.com/api-reference/speech-recognition/qwen-audio-asr/http-api — curl ASR sincrono (respuesta en `output.text`, NO `choices`) + `parameters.language_hints`
- https://docs.qwencloud.com/token-plan/best-practices/speech-recognition — payload ASR literal con key `sk-sp-`
- https://docs.qwencloud.com/developer-guides/speech/speech-to-text-models — limites/formatos/idiomas
- https://docs.qwencloud.com/developer-guides/speech/voice-list/qwen-audio-tts — voces
- https://docs.qwencloud.com/developer-guides/speech/qwen-audio-realtime y https://docs.qwencloud.com/api-reference/realtime-api/overview — realtime
- https://docs.qwencloud.com/token-plan/personal/token-plan-personal-overview — allowlist de audio en Token Plan
- https://docs.qwencloud.com/api-reference/preparation/error-messages — catalogo de errores

---

## 1. Autenticacion y hosts

| Key | Base REST | Host WebSocket (inferencia/TTS) | Host WebSocket (realtime) |
|---|---|---|---|
| `sk-sp-*` (Token Plan) | `https://token-plan.maas.qwencloudapi.com/api/v1` | `wss://token-plan.maas.qwencloudapi.com/api-ws/v1/inference` | `wss://token-plan.maas.qwencloudapi.com/api-ws/v1/realtime?model=...` |
| `sk-*` / `sk-ws-*` (pay-as-you-go) | `https://ap-southeast-1.maas.qwencloudapi.com/api/v1` | `wss://ap-southeast-1.maas.qwencloudapi.com/api-ws/v1/inference` | `wss://ap-southeast-1.maas.qwencloudapi.com/api-ws/v1/realtime?model=...` |

**Las bases Token Plan NO llevan region ID** (TP solo Singapur; la forma con region es la del
pay-as-you-go segun https://docs.qwencloud.com/developer-guides/getting-started/regions — la
forma pelada `maas.qwencloudapi.com` es el alias equivalente de Singapur). Header:
`Authorization: Bearer <KEY>`. Regla Token Plan: **las versiones exactas
`qwen-audio-3.0-tts-plus` / `qwen-audio-3.0-asr-flash` / `qwen-audio-3.0-realtime-plus` estan
en la allowlist; cualquier diferencia de version NO esta soportada** (la serie 3.1 —
`qwen-audio-3.1-tts-plus/flash`, que factura por tokens y si tiene HTTP nativo multi-voz — no
esta en TP).

**Correccion vs doc vieja**: `qwen-audio-3.0-tts-plus` NO es "SOLO WebSocket". La matriz
`tts-models` lista 3.0-plus como API WebSocket, pero la guia **Token Plan
best-practices/speech-synthesis documenta un one-shot HTTP** para este mismo modelo con key
`sk-sp-` (§2bis abajo). El error historico "current user api does not support http call"
correspondia a otras vias HTTP (multimodal-generation/compatible), no al endpoint
`SpeechSynthesizer`. La via WS sigue siendo la **verificada empiricamente** (2026-10-07) y la
default del script; la via HTTP one-shot la implementa como opcion `--http`. Si el smoke test
(F2) probara lo contrario, prevalece la evidencia empirica.

---

## 2. TTS por WebSocket (protocolo DashScope Inference, streaming duplex — default del script)

Handshake: `GET /api-ws/v1/inference HTTP/1.1` con `Upgrade: websocket`,
`Connection: Upgrade`, `Sec-WebSocket-Key`, `Sec-WebSocket-Version: 13`, `Authorization`.
Esperar `HTTP/1.1 101`. El cliente DEBE enmascarar los frames (RFC 6455); el servidor no.

### 2.1 run-task (iniciar sintesis)

```json
{
  "header": {"action": "run-task", "task_id": "<uuid4>", "streaming": "duplex"},
  "payload": {
    "task_group": "audio",
    "task": "tts",
    "function": "SpeechSynthesizer",
    "model": "qwen-audio-3.0-tts-plus",
    "parameters": {
      "text_type": "PlainText",
      "voice": "longanlingxin",
      "format": "mp3",
      "sample_rate": 22050,
      "volume": 50,
      "rate": 1,
      "pitch": 1
    },
    "input": {}
  }
}
```

- `"input": {}` es **OBLIGATORIO**: omitirlo → `InvalidParameter` "task can not be null" o cierre 1007.
- `format`: `mp3` | `wav` | `pcm` | `opus`. `sample_rate` validos: 8000/16000/22050/24000/44100/48000.
- `volume` 0-100 (default 50); `rate` y `pitch` 0.5-2.0 (default 1).
- Opcionales: `seed` (0-65535), `instruction` (<=100 chars, control de estilo en lenguaje natural).
- Respuesta esperada: evento `task-started`.

### 2.2 continue-task (enviar texto)

```json
{
  "header": {"action": "continue-task", "task_id": "<mismo>", "streaming": "duplex"},
  "payload": {"input": {"text": "Hello! This is a test."}}
}
```

- Limites de texto: **<=20000 caracteres por chunk**; el contador CJK cuenta 2 por char —
  el script trocea a 15000 chars por seguridad.
- Enviar todo el texto **sin demora** tras `task-started`: el servidor corta la conexion
  **23 s** sin recibir texto (`request timeout after 23 seconds`).
- Durante el envio llegan frames BINARIOS (opcode 0x2) con el audio, en orden, junto a
  eventos `result-generated` (pueden traer `usage.characters`).

### 2.3 finish-task (cerrar el texto — SIEMPRE)

```json
{
  "header": {"action": "finish-task", "task_id": "<mismo>", "streaming": "duplex"},
  "payload": {"input": {}}
}
```

No enviarlo = se pierde el final del audio. La tarea termina con evento `task-finished`
(despues de los ultimos frames binarios) o `task-failed` (con `header.error_code` /
`header.error_message`).

Errores tipicos de TTS: cierre 1007 (payload invalido), 401/403 (key↔host), `[tts:]Engine
error 411` (voz no valida para el modelo), `DataInspectionFailed` (moderacion del texto).

### 2bis. TTS HTTP one-shot (DOCUMENTADO PARA TOKEN PLAN — `sintetizar_voz.py --http`)

Source: https://docs.qwencloud.com/token-plan/best-practices/speech-synthesis (fetch 2026-11-09).
`POST {base}/services/audio/tts/SpeechSynthesizer` con `Authorization: Bearer $sk-sp-`.

```bash
curl -s -X POST "https://token-plan.maas.qwencloudapi.com/api/v1/services/audio/tts/SpeechSynthesizer" \
  -H "Authorization: Bearer $ANTHROPIC_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen-audio-3.0-tts-plus",
    "input": {
      "text": "<texto>",
      "voice": "longanlingxin",
      "format": "mp3",
      "sample_rate": 22050
    }
  }'
```

Campos documentados del one-shot: `model` (si), `input.text` (si), `input.voice` (si),
`input.format` (no; mp3|pcm|wav|opus, default mp3), `input.sample_rate` (no; default 22050).
Para pay-as-you-go el endpoint es el mismo bajo la base con region
(`https://ap-southeast-1.maas.qwencloudapi.com/api/v1/services/audio/tts/SpeechSynthesizer`) y
la doc general anade streaming SSE con header `X-DashScope-SSE: enable` (chunks en
`output.audio.data` base64; la frame final trae `output.finish_reason=stop` + URL completa).

Respuesta (literal de la doc, formateada):

```json
{
  "output": {
    "audio": {
      "data": "",
      "id": "audio_xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
      "expires_at": 1792079569,
      "url": "https://example.com/output.wav"
    },
    "finish_reason": "stop"
  },
  "usage": { "characters": 22 },
  "request_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
}
```

- `output.audio.url` = archivo completo, **valido 24 h** → descargar ya (el script `--http` lo
  hace solo); `output.audio.expires_at` = fecha de expiracion; `usage.characters` = billables
  (la serie 3.0 factura por caracteres; la 3.1 —fuera de TP— factura por tokens e incluye
  `usage.input_tokens/output_tokens`).
- `data` llega vacio en modo no-streaming: la via es SIEMPRE la URL.
- **Ojo**: `rate`, `pitch`, `volume`, `seed` e `instruction` NO estan en la lista de campos del
  one-shot — son del protocolo WS; el script `--http` los ignora con aviso.

### 2ter. Voces

- **Voces de sistema verificadas en Token Plan (unicas 2):** `longanlingxin` (femenina, calida,
  default) y `longanlufeng` (masculina). Catalogo oficial: chino/ingles; **ESPANOL VERIFICADO
  EMPIRICAMENTE 2026-09-28** (roundtrip TTS→ASR con guion en espanol directo inteligible).
- **DISCREPANCIA DOCUMENTAL (no afirmar usable):** la propia guia TP de sintesis usa como voz
  default `longanhuan_v3.6`, pero esa voz pertenece a `qwen-audio-3.0-tts-flash` (modelo NO esta
  en la allowlist TP) y choca con la regla "la voz debe coincidir con la version del modelo"
  → tratar `longanhuan_v3.6` como **sin verificar**: probar antes de afirmarla; las rutas
  seguras siguen siendo `longanlingxin` / `longanlufeng`.
- **Base voices (voice cloning):** 500+ identificadores `qwen-audio-3.0-tts-plus-{suffix}`
  creados con la API de enrolamiento (ver §5). Idiomas no verificados; el catalogo oficial
  (597 voces) solo declara Chinese/English — NO hay base voices en espanol.
- **Alternativa en espanol:** la serie **Qwen3-TTS** (pay-as-you-go, HTTP REST estilo CosyVoice,
  mismo endpoint `SpeechSynthesizer`) incluye voces multilingues con espanol (p.ej. `Sonrisa`,
  `Bodega`). **NO esta en la allowlist del Token Plan** — requiere key `sk-*` con saldo.
- Lista completa de voces: https://docs.qwencloud.com/developer-guides/speech/voice-list/qwen-audio-tts

---

## 3. ASR sincrono por HTTP (qwen-audio-3.0-asr-flash)

Endpoint: `POST {base}/services/aigc/multimodal-generation/generation` (el mismo de
imagenes). Headers: `Content-Type: application/json`, `Authorization: Bearer <KEY>`,
`X-DashScope-SSE: disable`.

curl literal (adaptado al host del plan):

```bash
curl -X POST https://token-plan.maas.qwencloudapi.com/api/v1/services/aigc/multimodal-generation/generation \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -H "X-DashScope-SSE: disable" \
  -d '{
    "model": "qwen-audio-3.0-asr-flash",
    "input": {
      "messages": [
        {"role": "user", "content": [
          {"type": "input_audio", "input_audio": {"data": "https://example.com/audio/demo.wav"}}
        ]}
      ]
    },
    "parameters": {"format": "wav"}
  }'
```

Respuesta — **el texto va en `output.text`, NO en `choices`** (no asumir el formato de
imagenes):

```json
{
  "output": {"text": "Hola, esto es una prueba de transcripcion."},
  "usage": {"characters": 0},
  "request_id": "c82147d9-...",
  "code": "", "message": ""
}
```

Variantes de forma vistas (fallbacks que implementa el script): `output.output.sentence.text`
y, excepcionalmente, `output.choices[].message.content[].text`.

Parametros (tabla oficial TP + HTTP API, verificada 2026-11-09):

- `format` (obligatorio): extension sin punto (`mp3|wav|opus|...`), coincide con el tipo del audio.
- `sample_rate` (string, opcional): solo si hay que forzarlo.
- `input_audio.data`: URL publica o **data URI** `data:audio/mpeg;base64,...` (limite
  10 MB por item: `Exceeded limit on max bytes per data-uri item: 10485760`).
- **`language_hints` (array[string], opcional) — EXISTE**: hasta **4 codigos ISO** (si se pasan
  mas, solo valen los primeros 4); omitido = autodeteccion. Especificarlo **mejora la precision**
  cuando el idioma se conoce. Codigos soportados por `qwen-audio-3.0-asr-flash`: zh en ja ko vi th
  id ms tl hi ar fr **es** de pt ru it nl sv da fi no el pl cs hu ro bg hr sk (la serie 3.1 —
  fuera de TP— anade tr fa mr ne ky az y otros). En el script: `--language-hints es,en`.
  **CORREGIDO**: la doc anterior de esta skill decia "no hay parametro `language` en este modo" —
  era falso para el modo HTTP no real time: `language_hints` esta documentado en
  https://docs.qwencloud.com/token-plan/best-practices/speech-recognition y en el API reference.
- Context enhancement (**experimental**): anadir ANTES del audio, en el mismo content array:
  `{"type": "input_text", "text": "terminos y nombres esperados"}`. Limites oficiales: max 5
  mensajes por tipo (`input_text` y `text` de role assistant), <=400 caracteres de texto de
  contexto por turno (el exceso se trunca), y el mensaje con `input_audio` debe ser el ULTIMO.
- Hotwords: `vocabulary` instantaneo (objeto {texto: peso}, peso 1-5 o 50 = "super", max 50
  super; soportado inline por 3.0-asr-flash y 3.1) o `vocabulary_id` precompilado (creado con la
  API de hot words). `language_hints` y hotwords son compatibles entre si.
- SSE: `X-DashScope-SSE: enable` para streaming de parciales — solo para audio **>= 1 minuto**.

Limites: duracion **<=5 min** (1-300 s), tamano **<=10 MB**. Formatos (17): aac amr avi flac
flv m4a mkv mov mp3 mp4 mpeg ogg opus wav webm wma wmv. Idiomas: autodeteccion (~30,
**incluido espanol**) o `language_hints`.

Errores: `InvalidFile.AudioLengthError`, `"The audio is empty"`, `InvalidFile.DownloadFailed`,
`DataInspectionFailed`, 429/Throttling, 401 InvalidApiKey.

---

## 4. ASR asincrono filetrans (NO esta en Token Plan — SOLO pay-as-you-go)

Para audios largos: modelo `qwen-audio-3.0-asr-flash-filetrans`, **<=12 h / <=2 GB**,
con diarizacion de hablantes. Requiere key pay-as-you-go (`sk-*`). **No intentar con `sk-sp-*`**
(no esta en la allowlist TP).

```bash
curl -X POST https://ap-southeast-1.maas.qwencloudapi.com/api/v1/services/audio/asr/transcription \
  -H "Authorization: Bearer $DASHSCOPE_API_KEY" \
  -H "Content-Type: application/json" \
  -H "X-DashScope-Async: enable" \
  -d '{
    "model": "qwen-audio-3.0-asr-flash-filetrans",
    "input": {"file_urls": ["https://example.com/entrevista.mp3"]},
    "parameters": {"channel_id": [0], "with_timestamp": false, "language_hints": ["es"]}
  }'
```

Devuelve `output.task_id`. Poll (hasta `SUCCEEDED`/`FAILED`):

```bash
curl -X GET https://ap-southeast-1.maas.qwencloudapi.com/api/v1/tasks/{task_id} \
  -H "Authorization: Bearer $DASHSCOPE_API_KEY"
```

El resultado llega en `output.results[].transcription_url` (JSON con la transcripcion
completa; diarizacion con `diarization_enabled: true` — manteniendo el audio <=2 h — y
`speaker_count` 2-100 como referencia; cada pista (`channel_id`) se factura aparte).

---

## 5. Voice cloning (enrolamiento de voz)

`POST {base}/services/audio/tts/customization` con `model: qwen-voice-enrollment`:

```json
{
  "model": "qwen-voice-enrollment",
  "input": {"action": "create", "target_model": "qwen-audio-3.0-tts-plus",
            "preferred_name": "mi-voz", "audio": {"data": "https://.../muestra.wav"}}
}
```

La voz creada se usa en TTS como `voice: "qwen-audio-3.0-tts-plus-<suffix>"` (una de las
500+ base voices dinamicas). El `target_model` de la voz DEBE coincidir con el `model` de la
sintesis (otro modelo → fallo). Verificar disponibilidad del endpoint de personalizacion segun
el plan antes de automatizarlo.

---

## 6. Realtime (qwen-audio-3.0-realtime-plus — DOCUMENTAL: en allowlist TP, sin script)

Dialogo de voz en tiempo real, estilo **OpenAI Realtime API**. El modelo ESTA en la allowlist
del Token Plan y la conexion tiene **endpoint TP documentado**:

```
wss://token-plan.maas.qwencloudapi.com/api-ws/v1/realtime?model=qwen-audio-3.0-realtime-plus
```

(pay-as-you-go: `wss://ap-southeast-1.maas.qwencloudapi.com/api-ws/v1/realtime?model=...`;
las bases TP no llevan region ID).

- Eventos clave: `session.update` (voz, formatos), `input_audio_buffer.append` (audio
  entrante: **PCM 16 kHz mono** en base64), `response.audio.delta` (audio saliente:
  **PCM 24 kHz**).
- Voces: `longanqian`, `longanlingxin`, `longanlingxi`, `longanxiaoxin`, `longanlufeng`.
  **Soporta espanol.**
- Limites: ~50 turnos / 300 s por sesion.
- Sigue **sin script** (no es util desde batch: requiere micromono/duplex interactivo), pero ya
  con la URL TP exacta documentada — ruta futura clara para un cliente `realtime` propio.
  Fuentes: https://docs.qwencloud.com/developer-guides/speech/qwen-audio-realtime ,
  https://docs.qwencloud.com/api-reference/realtime-api/overview y
  https://docs.qwencloud.com/token-plan/personal/token-plan-personal-overview#supported-models.

---

## 7. Costos (orientativos; verificar la web)

| Operacion | Precio |
|---|---|
| TTS `qwen-audio-3.0-tts-plus` (WS o HTTP one-shot) | ~$0.20 / 10.000 caracteres — factura por **caracteres** (`usage.characters`) |
| ASR `qwen-audio-3.0-asr-flash` | ~$0.000035 / segundo de audio |

Con Token Plan (`sk-sp-*`) la liquidacion real es en **Credits** (ver Usage en la consola); los
USD son referencia de costo relativo. Nota de terminos: la key Token Plan esta orientada a
**uso interactivo**; para automatizacion intensiva por lotes (audiolibros, transcripcion masiva)
usar key pay-as-you-go (`sk-*`).
