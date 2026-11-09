---
name: qwen-audio
description: >
  Voz con QwenCloud (Token Plan sk-sp- resuelta sola): sintetiza voz TTS (narrar, locucion,
  doblaje) con qwen-audio-3.0-tts-plus por WebSocket (default, verificada empiricamente) o por
  HTTP one-shot --http (via documentada para Token Plan: POST /services/audio/tts/
  SpeechSynthesizer → output.audio.url); transcribe audio/video a texto ASR (subtitulos,
  grabaciones) con qwen-audio-3.0-asr-flash HTTP sincrono (<=5 min, language_hints hasta 4
  idiomas). Usa SIEMPRE que el usuario pida sintetizar voz o transcribir audio con IA de Qwen,
  aunque no nombre la herramienta. Voces de sistema verificadas: longanlingxin (F) y
  longanlufeng (M), espanol verificado empiricamente. Secciones documentales sin script:
  filetrans para audios largos (pay-as-you-go SOLO) y realtime qwen-audio-3.0-realtime-plus
  (URL TP exacta abajo). NO para: video con audio sincrono → skill qwen-video; audio largo
  (>5 min) con key sk-sp- → no soportado (filetrans exige pay-as-you-go).
license: MIT
metadata:
  version: "3.0"
  split-de: "qwen-tools v2.0"
  api_base_rest: "https://token-plan.maas.qwencloudapi.com/api/v1"
  ws_inference: "wss://token-plan.maas.qwencloudapi.com/api-ws/v1/inference"
  ws_realtime: "wss://token-plan.maas.qwencloudapi.com/api-ws/v1/realtime"
---

# QWEN-AUDIO — sintesis (TTS) y transcripcion (ASR) con QwenCloud

## DISPATCH (leer primero — elige el camino y NO leas los demas)

| Que pide el usuario | Camino |
|---|---|
| Voz / locucion / narrar / leer en voz alta / doblaje (texto → audio) | `scripts\sintetizar_voz.py` (WS default; `--http` one-shot). Reference: `references\api-qwen-audio.md` §1-§2 |
| Transcribir audio/video a texto / subtitulos (<=5 min) | `scripts\transcribir_audio.py`. Reference: §3 |
| Transcribir audio LARGO (>5 min, <=12 h, diarizacion) | **DOCUMENTAL**: filetrans, SOLO pay-as-you-go (fuera de Token Plan). Reference: §4 |
| Dialogo de voz en tiempo real | **DOCUMENTAL**: realtime `qwen-audio-3.0-realtime-plus` (URL TP abajo, sin script). Reference: §6 |

Ruta canonical: `py "%USERPROFILE%\.config\opencode\skills\qwen-audio\scripts\<script>.py"`.

## KEY Y BASES — resolucion automatica (familia B, REST + WS; TP PRIMERO)

**Nunca imprimir la key ni el body** (stdout, stderr ni `--out`). Sin ninguna key → exit 2 con
instruccion (crear key en https://home.qwencloud.com/api-keys). Precedencia: 1.
`DASHSCOPE_API_KEY`, 2. `ANTHROPIC_AUTH_TOKEN`, 3. `~/.local/share/opencode/auth.json`
(`alibaba-token-plan` / `alibaba-token-plan-cn`). Host por prefijo (o `--base-url` que manda):

| Key | REST | WS inferencia (TTS) | WS realtime |
|---|---|---|---|
| `sk-sp-*` (Token Plan) | `https://token-plan.maas.qwencloudapi.com/api/v1` | `wss://token-plan.maas.qwencloudapi.com/api-ws/v1/inference` (empirico) | `wss://token-plan.maas.qwencloudapi.com/api-ws/v1/realtime?model=qwen-audio-3.0-realtime-plus` (documentado) |
| `sk-*` / `sk-ws-*` (pay-as-you-go) | `https://ap-southeast-1.maas.qwencloudapi.com/api/v1` | `wss://ap-southeast-1.maas.qwencloudapi.com/api-ws/v1/inference` | `wss://ap-southeast-1.maas.qwencloudapi.com/api-ws/v1/realtime?model=...` |

**Las bases Token Plan NO llevan region ID** (Token Plan solo existe en Singapur; la forma con
region es la del pay-as-you-go segun doc `developer-guides/getting-started/regions`; la forma
pelada `maas.qwencloudapi.com` = alias equivalente de Singapur). Allowlist TP de audio
(exact-string): `qwen-audio-3.0-tts-plus`, `qwen-audio-3.0-asr-flash`,
`qwen-audio-3.0-realtime-plus` — cualquier otra version → `Model not exist`. Consumo en
**Credits** (TTS por caracteres, ASR por segundo de audio); USD = referencia. Con key `sk-sp-*`
el script TTS **reintenta una vez** contra el host pay-as-you-go si el handshake WS falla
(avisa por stderr que host funciono). Key `sk-sp-*` = uso INTERACTIVO; lotes (audiolibros,
transcripcion masiva) → pay-as-you-go.

## TTS — sintetizar_voz.py (qwen-audio-3.0-tts-plus)

**Dos vias, la default es WebSocket** (verificada empiricamente 2026-10-07, streaming duplex).
Desde 2026-11 la doc de Token Plan documenta ADEMAS una via **HTTP one-shot** para este mismo
modelo — el error historico "current user api does not support http call" aplicaba a otras vias
HTTP (multimodal/compatible), no a este endpoint:

```
POST https://token-plan.maas.qwencloudapi.com/api/v1/services/audio/tts/SpeechSynthesizer
Authorization: Bearer <sk-sp-*>
{"model": "qwen-audio-3.0-tts-plus",
 "input": {"text": "<texto>", "voice": "longanlingxin", "format": "mp3", "sample_rate": 22050}}
```

→ respuesta `output.audio.url` (**expira en 24 h** — el script `--http` la descarga solo),
`output.audio.expires_at`, `usage.characters` (billables). Campos documentados del one-shot:
`text` (obligatorio), `voice` (obligatorio), `format` mp3|pcm|wav|opus (default mp3),
`sample_rate` (default 22050). Los extras de estilo (`rate`, `pitch`, `volume`, `seed`,
`instruction`) son del protocolo WS: `sintetizar_voz.py --http` los IGNORA con aviso — para
ellos usa la via WS (default). Si `--http` fallara en vivo, la via WS sigue siendo la ruta
verificada.

```
:: WS (default)
py "%USERPROFILE%\.config\opencode\skills\qwen-audio\scripts\sintetizar_voz.py" --text-file guion.txt --output voz.mp3
:: HTTP one-shot
py ...sintetizar_voz.py --text "Hola, prueba" --output voz.mp3 --http
py ...sintetizar_voz.py --text "Hello world" --voice longanlufeng --format mp3 --sample-rate 22050 --rate 1.1 --output voz.mp3
```

**Voces de sistema verificadas en Token Plan (unicas 2): `longanlingxin` (femenina, calida,
default) y `longanlufeng` (masculina)** — chino/ingles y **ESPANOL VERIFICADO empiricamente
2026-09-28** (roundtrip TTS→ASR: guion en espanol directo inteligible; `--instruction` en ingles
de apoyo, opcional <=100 chars). Ademas 500+ "base voices" `qwen-audio-3.0-tts-plus-{suffix}`
(voice cloning; el catalogo oficial 597 voces solo declara Chinese/English — NO hay base voices
en espanol). Alternativa con voces nativas en espanol: serie Qwen3-TTS **pay-as-you-go** (key
`sk-*`, NO Token Plan).

**DISCREPANCIA DOCUMENTAL (no afirmar usable):** la guia TP de sintesis trae como voz default
`longanhuan_v3.6`, pero esa voz pertenece a `qwen-audio-3.0-tts-flash` (modelo FUERA de la
allowlist TP) → contradice la regla "la voz debe coincidir con la version del modelo". NO la
des como valida: mantener `longanlingxin`/`longanlufeng` y probar `longanhuan_v3.6` antes de
afirmar nada (checklist F2).

Parametros WS del script: `--format mp3|wav|pcm|opus`, `--sample-rate`
8000/16000/22050/24000/44100/48000 (22050), `--rate` 0.5-2.0, `--pitch` 0.5-2.0, `--volume` 0-100
(50), `--seed` 0-65535, `--instruction`, `--output` obligatorio, `--text-file` (Windows).
Protocolo WS (el script ya lo implementa — no reimplementar): handshake `GET /api-ws/v1/inference`
→ 101; `run-task` con `"input": {}` OBLIGATORIO; `continue-task` (chunks <=20000 chars, CJK
cuenta 2 → el script trocea a 15000; enviar TODO sin demora — el servidor corta a los **23 s**
sin texto); `finish-task` **SIEMPRE** (o se pierde el final del audio); frames binarios = audio;
`task-finished`. Costo orientativo: ~$0.20 / 10.000 caracteres (3.0-plus factura por caracteres;
la serie 3.1 factura por tokens — no esta en TP).

## ASR — transcribir_audio.py (qwen-audio-3.0-asr-flash, HTTP sincrono)

```
py "%USERPROFILE%\.config\opencode\skills\qwen-audio\scripts\transcribir_audio.py" --audio voz.mp3 --output texto.txt
py ...transcribir_audio.py --audio https://ejemplo.com/clip.wav --language-hints es,en --json
```

Limites: duracion **1-300 s (<=5 min)**, tamano <=10 MB; local <=7 MB → data URI base64
automatico; mas grande → subir a URL publica. 17 formatos (aac amr avi flac flv m4a mkv mov mp3
mp4 mpeg ogg opus wav webm wma wmv; `format` se deduce de la extension). Autodeteccion de idioma
(~30, **incluido espanol**). **CORREGIDO vs doc vieja: SI existe control de idioma** —
`parameters.language_hints`: array de codigos ISO (p.ej. `["es","en"]`), **hasta 4** (excedentes
ignorados); especificarlo sube la precision cuando el idioma se conoce; omitido = autodeteccion.
El flag `--language-hints es,en` lo envia. **El texto viene en `output.text`, NO en `choices`**
(fallbacks del script: `output.output.sentence.text` y `choices[].message.content[].text`).
`--sample-rate N` (opcional, default `None` = el servidor deduce la frecuencia) lo envia como
`parameters.sample_rate` (string) solo cuando se indica — util si la API no detecta bien el sample rate.
`--context "texto"` = context enhancement experimental (nombres/terminos; limite real: <=5
mensajes por tipo y <=400 chars por turno). Hotwords instantaneas (`parameters.vocabulary`,
peso 1-5 o 50 = super) y precompiladas (`vocabulary_id`) documentadas en la reference §3. SSE
streaming solo para audio >=1 min. Costo orientativo: ~$0.000035 / segundo de audio.

## FILETRANS (DOCUMENTAL — pay-as-you-go SOLO, fuera de Token Plan)

Audios largos: `qwen-audio-3.0-asr-flash-filetrans`, **<=12 h / <=2 GB**, diarizacion,
`POST {base}/services/audio/asr/transcription` async + poll `/tasks/{id}`; resultado en
`output.results[].transcription_url`. Requiere key `sk-*` con saldo — **NO la intentar con
`sk-sp-*`** (no esta en la allowlist TP). Ejemplo literal: reference §4.

## REALTIME (DOCUMENTAL — sin script; URL Token Plan exacta)

Dialogo de voz en tiempo real, estilo OpenAI Realtime. **Token Plan tiene endpoint documentado:**

```
wss://token-plan.maas.qwencloudapi.com/api-ws/v1/realtime?model=qwen-audio-3.0-realtime-plus
```

(con pay-as-you-go: `wss://ap-southeast-1.maas.qwencloudapi.com/api-ws/v1/realtime?model=...`).
Eventos: `session.update`, `input_audio_buffer.append` (PCM 16 kHz mono base64 entrante),
`response.audio.delta` (PCM 24 kHz saliente). Voces: `longanqian`, `longanlingxin`,
`longanlingxi`, `longanxiaoxin`, `longanlufeng` — **soporta espanol**. Limites ~50 turnos /
300 s por sesion. `qwen-audio-3.0-realtime-plus` SI esta en la allowlist TP, pero **no hay
script** (requiere micromono/duplex interactivo, inutil en batch): documentado como ruta futura
con la URL TP verificada en doc (antes esta seccion caia sin endpoint concreto).

## ERRORES (dominio audio)

| Situacion | Accion |
|---|---|
| HTTP/WS 401 / `InvalidApiKey` / WS 401-403 | key invalida o key↔host incorrectos (`sk-sp-*` ⇒ host token-plan). Detenerse |
| `Model not exist` | modelo fuera de allowlist TP (usar 3.0-tts-plus / 3.0-asr-flash / exact-string) |
| HTTP 429 / `Throttling*` | ASR reintenta 2x (5-15 s); TTS → esperar y reintentar; TP: esperar 1 min |
| `DataInspectionFailed` | moderacion del texto/audio → reescribir guion / cambiar audio |
| HTTP 400 `InvalidParameter` (TTS) | voz no valida para el modelo → longanlingxin/longanlufeng; `language_hints` >4 = los primeros 4 |
| `[tts:]Engine error 411` | voz no valida para el modelo |
| `request timeout after 23 seconds` | texto TTS enviado tarde tras `task-started` — el script ya lo envia sin demora |
| WS 1007 / `task can not be null` | `run-task` sin `"input": {}` — no debe ocurrir con el script |
| `InvalidFile.AudioLengthError` / `The audio is empty` / `InvalidFile.DownloadFailed` | ASR: audio fuera de 1-300 s / vacio / URL no descargable |
| `Exceeded limit on max bytes per data-uri item: 10485760` | audio >10 MB en base64 → URL publica |
| `Arrearage` | saldo pendiente (pay-as-you-go): regularizar pago |

**Exit codes**: `0` OK · `1` error de API/WS/HTTP/audio/descarga · `2` configuracion/uso (falta
key, texto o audio, flag invalido). Sin exit 3: este dominio NO consume el presupuesto diario de
busqueda.

## ARCHIVOS

```
qwen-audio/
├── SKILL.md
├── README.md
├── scripts/
│   ├── sintetizar_voz.py      # TTS: WS default + --http one-shot (SpeechSynthesizer)
│   └── transcribir_audio.py   # ASR HTTP sincrono (language_hints hasta 4)
└── references/api-qwen-audio.md  # WS literal run/continue/finish, TTS HTTP, curl ASR, filetrans, voices, realtime
```

Referencias a un solo nivel: leer la reference del dominio SOLO cuando el body de esta skill no
baste.
