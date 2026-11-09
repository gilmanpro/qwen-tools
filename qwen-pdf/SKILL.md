---
name: qwen-pdf
description: >
  Lee y entiende documentos PDF con QwenCloud (via Chat Completions o DashScope, content
  type:"file" con file_url o file_data base64): resumir un informe, responder preguntas
  sobre un PDF local o URL, extraer conclusiones — el modelo parsea texto e imagenes del
  documento (limites 150 MB / 256 paginas). Usa SIEMPRE que el usuario pida leer, resumir
  o analizar un PDF con IA de Qwen, aunque no nombre la herramienta. Script leer_pdf.py
  solo-stdlib con stream (primer token hasta 300 s) y key sk-sp- resuelta sola. NUNCA via
  Responses API: devuelve 200 SIN entregar el archivo al modelo (respuesta vacia/trampa).
  NO para: transcribir audio → qwen-audio; entender una imagen → vision directa; generar
  un PDF → ofimatica.
license: MIT
metadata:
  version: "3.0"
  split-de: "qwen-tools v2.0"
  api_base_rest: "https://token-plan.maas.qwencloudapi.com/compatible-mode/v1"
---

# QWEN-PDF — Lectura y entendimiento de PDF (Chat Completions / DashScope)

El modelo parsea el PDF (texto + imagenes contadas como input tokens) y responde a tu
pregunta sobre el documento. Script `scripts\leer_pdf.py` solo-stdlib: ruta local →
base64 automatico (con `filename` obligatorio) o URL; pregunta via **stream SSE**;
salida texto o JSON unico; contrato de exit codes 0/1/2.

## ⚠️ NUNCA POR RESPONSES API (trampa documentada)

> **La Responses API NO soporta PDF understanding.** Si pasas el archivo por
> `/responses`, la peticion **devuelve HTTP 200 con una respuesta normal del modelo que
> NO ha visto el PDF** — ni error ni senal: el modelo alucina sobre un documento que no
> recibio. Usa SIEMPRE Chat Completions (`/chat/completions`) o la via DashScope. El
> script ya lo hace; no lo "modernices" a Responses.

## MODELOS SOPORTADOS (doc oficial 2026-11-09)

`qwen3.8-max`, `qwen3.8-max-0902`, `qwen3.8-flash` (los tres en la allowlist Token Plan;
el script default es `qwen3.8-flash` por costo).

## LIMITES Y RENDIMIENTO

| Item | Valor |
|---|---|
| Tamano maximo del archivo | **150 MB** |
| Paginas maximas | **256** |
| First-token | hasta **300 s** (el parsing pesa) — por eso `--timeout` default = 300 |
| base64 | infla el cuerpo ~1/3: 150 MB → ~200 MB de request. **Para archivos grandes usa `--file-url` (URL publica descargable por el servidor), no base64** |

**Stream recomendado** (y el script lo implementa): sin stream hay que aguantar el
parsing completo en una sola espera; con SSE el texto llega en vivo y `stream_options:
{"include_usage": true}` devuelve los tokens al final.

## USO

```
:: resumen de un PDF local (base64 automatico con filename)
py "%USERPROFILE%\.config\opencode\skills\qwen-pdf\scripts\leer_pdf.py" --file informe.pdf
:: pregunta concreta, JSON unico
py "%USERPROFILE%\.config\opencode\skills\qwen-pdf\scripts\leer_pdf.py" --file informe.pdf --pregunta "cuales son las conclusiones" --json
:: PDF en URL (obligado si se acerca a 100-150 MB)
py "%USERPROFILE%\.config\opencode\skills\qwen-pdf\scripts\leer_pdf.py" --file-url "https://.../paper.pdf" --pregunta "resume" --out .tmp\respuesta.json
```

Flags: `--file` / `--file-url` (excluyentes, uno obligatorio), `--pregunta` (default
"Resume este documento"), `--model`, `--timeout` (default **300**), `--json`, `--out`
(ruta DENTRO del proyecto), `--base-url` (manda sobre la cadena). Pre-validaciones gratis
sin HTTP (exit 2): archivo inexistente, magic bytes no `%PDF`, >150 MB, URL no http(s).

Salida `--json`: `{"ok":true,"model","base","origen","answer","paginas","usage":{input_
tokens,output_tokens,total_tokens,x_tools},"seconds}`. Sin `--json`: el texto se imprime
**en vivo** (stream) y el resumen va por stderr. Exit codes: `0` OK · `1` API/red (tras
agotar cadena y reintentos 429) · `2` configuracion (falta key/parametro, PDF invalido).

## KEY Y BASES — resolucion automatica. Nunca imprimir la key ni el body

(stdout, stderr ni `--out`). Sin ninguna key → exit 2 con instruccion (crear key en
https://home.qwencloud.com/api-keys).

**Familia B — precedencia**: 1. `DASHSCOPE_API_KEY`, 2. `ANTHROPIC_AUTH_TOKEN`,
3. `~/.local/share/opencode/auth.json` (providers `alibaba-token-plan` / `-cn`). Host por
prefijo de la key (o `--base-url`, que manda sobre todo y salta la cadena):

| Key | Cadena de bases (`/compatible-mode/v1` + `/chat/completions`) |
|---|---|
| `sk-sp-*` (Token Plan) | 1. `https://token-plan.maas.qwencloudapi.com/compatible-mode/v1` (OFICIAL documentada — las bases TP NO llevan region ID; **200 verificada en vivo 2026-11-09** via `/chat/completions`, evidencia `.tmp\qwen-split\tests\qwen-pdf\leer_pdf.json`) · 2. `https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1` (LEGACY — **fallback, no necesaria desde 2026-11-09**) · 3. `https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1` (otros workspaces) |
| `sk-*` / `sk-ws-*` (pay-as-you-go) | `https://maas.qwencloudapi.com/compatible-mode/v1` · region SG oficial: `https://ap-southeast-1.maas.qwencloudapi.com/compatible-mode/v1` (las keys son region-specific) |

**Allowlist Token Plan** (`sk-sp-*`): cualquier otro modelo → `Model not exist`. Consumo
en **Credits**; los USD son referencia de costo relativo (pueden cambiar). Key `sk-sp-*`
orientada a uso interactivo; lotes/produccion → key pay-as-you-go con saldo.

## BILLING

- **Input tokens**: el texto e imagenes parseados del PDF se cuentan como tokens de input
  al precio estandar del modelo (un PDF de 100 paginas puede inflar la cuenta).
- **Fee `document_parsing` por pagina parseada**: $0.003/pagina Beijing (China North 2) ·
  $0.0033/pagina Singapore. Se ve en `usage.x_tools.pdf_page_parser.count`
  (={"count":N,"strategy":"normal"}) — **solo si mandas `include_tool_usage:true`**: via
  SDK OpenAI con `extra_body={"include_tool_usage": True}`; via raw HTTP
  (este script) **TOP-LEVEL en el body** (nunca anidado dentro de extra_body ni de
  stream_options).
- **NOTA HONESTA sobre Token Plan**: el fee `document_parsing` **NO esta documentado para
  keys `sk-sp-` (Token Plan)**. Los tokens TP se consumen en Credits, pero el fee por
  paginas podria liquidarse como PAYG aparte → **verificar en la factura (账单) tras la
  primera prueba; con TP existe riesgo de facturacion PAYG del fee**. Los numeros de esta
  tabla son precios de lista pay-as-you-go.

## ERRORES

| Situacion | Accion |
|---|---|
| Respuesta "normal" pero el modelo no vio el PDF | llamaste a `/responses` — NO soporta PDF (200 sin entregar el archivo). Usa este script (Chat Completions) |
| HTTP 400 `InvalidParameter` / payload rechazado | PDF >150 MB o >256 pag, o base64 >limite de body → `--file-url` |
| `url` con array de URLs | no soportado: `file_url` acepta UN string |
| Falta `filename` en base64 | obligatorio con `file_data` — el script lo pone solo |
| HTTP 401 / `InvalidApiKey` | key invalida o key↔host (`sk-sp-` ⇒ host token-plan). Detenerse |
| HTTP 429 / `Throttling*` | el script reintenta 2x (espera 10 s); persiste → reducir ritmo |
| `Model not exist` | modelo fuera de la allowlist Token Plan |
| Timeout / conexion cortada | parsing largo: subir `--timeout` (default 300) o dividir el PDF |
| `Arrearage` | saldo pendiente (pay-as-you-go): regularizar pago |

Detalle de bodies y campos: `references\api-pdf.md`.

## ARCHIVOS

```
qwen-pdf/
├── SKILL.md
├── README.md
├── scripts/
│   └── leer_pdf.py             # Chat Completions + stream SSE (solo-stdlib)
└── references/
    └── api-pdf.md              # bodies literales OpenAI-compat/DashScope, usage, errores
```
