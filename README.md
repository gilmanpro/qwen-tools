# qwen-tools

Repositorio **multi-skill** de capacidades QwenCloud / Token Plan para agentes. Desde
2026-11-09 el antiguo monolito se desfragmento en **10 skills independientes**, una por
funcion. Cada skill es un paquete [Agent Skills](https://agentskills.io) autosuficiente:
un `SKILL.md` (dispatch + reglas), su(s) script(s) Python **solo-stdlib** (sin
`pip install`, compatible con `py` de Windows) y sus `references/`. La key `sk-sp-` del
Token Plan se resuelve sola desde `auth.json`/env; no hay dependencias externas.

**Layout:** una carpeta por skill en la raiz del repo. Cada carpeta = una skill que se
instala y se carga por separado. Elige solo las que necesites.

## Indice de skills

| Skill | Que hace | Script(s) | Modelo(s) Token Plan | Fee Credits (ref.) |
|---|---|---|---|---|
| `qwen-web-search` | Buscar en la web con fuentes citables (Responses API `web_search`) | `buscar_web.py` | `qwen3.8-flash` (default) / `qwen3.8-max` | web_search $10/1k llamadas (agent, SG) |
| `qwen-image-search` | Buscar fotos por texto (`web_search_image`) e imagen inversa (`image_search`) | `buscar_imagen.py` | `qwen3.8-flash` / `qwen3.8-max` | $8/1k SG · $6.881/1k Beijing · max 100 resultados |
| `qwen-web-extractor` | Leer el contenido completo de 1+ URLs (Responses API `web_extractor`) | `extraer_web.py` | `qwen3.8-flash` / `qwen3.8-max` | gratis por tiempo limitado (+ fee del search interno si se lanza) |
| `qwen-code-interpreter` | Python en el sandbox remoto (Responses API `code_interpreter`) — uso exclusivo @5-dev | `ejecutar_codigo.py` | `qwen3.8-flash` / `qwen3.8-max` | temporalmente gratis (solo tokens) |
| `qwen-pdf` | Leer/entender un PDF (Chat Completions / DashScope, `type:"file"`) | `leer_pdf.py` | `qwen3.8-flash` / `qwen3.8-max` / `qwen3.8-max-0902` | pdf_page_parser $0.0033/pag SG · $0.003/pag Beijing |
| `qwen-mcp` | Conectar el modelo a un servidor MCP externo (Responses API `mcp`, solo SSE) | `consultar_mcp.py` | cualquier modelo de texto | tokens + fees del server. **SOLO pay-as-you-go**: trampa-200 en Token Plan |
| `qwen-function-calling` | Tools client-side (loop modelo <-> tu codigo): documentacion + plantilla | `plantilla_function_calling.py` | todos los modelos de texto | solo tokens (sin fee de herramienta) |
| `qwen-imagen` | Generar/editar imagenes (Qwen-Image / Wan2.7, REST sincrona) | `generar_imagen.py` | `qwen-image-3.0-pro` / `wan2.7-image-pro` / `wan2.7-image` | $0.03-0.075 por imagen exitosa (fallidas NO se facturan) |
| `qwen-video` | Generar video (HappyHorse 1.1 t2v/i2v/r2v + `wan3.0-video`, REST asincrona) | `generar_video.py` | `happyhorse-1.1-*` / `wan3.0-video` | ~$0.07/s happyhorse · $0.035-0.14/s wan3.0 segun resolucion |
| `qwen-audio` | TTS por WS o HTTP (`--http`) y ASR; realtime y filetrans como secciones documentales | `sintetizar_voz.py` · `transcribir_audio.py` | `qwen-audio-3.0-tts-plus` / `qwen-audio-3.0-asr-flash` | TTS ~$0.20/10k chars · ASR ~$0.000035/s audio |

Cada skill repite su propia seccion "KEY Y BASES": no hay dependencia entre ellas ni una
skill comun compartida.

## Instalacion

Copia (o clona) **las carpetas de skill que necesites** al directorio de skills de tu
arnes; opencode resuelve las skills desde ahi:

```
~/.config/opencode/skills/qwen-web-search/
~/.config/opencode/skills/qwen-video/
...
```

Tambien funciona en `~/.agents/skills/` o en el proyecto bajo `.opencode/skills/`.

**Migracion desde el monolito.** Antes todo vivia en una unica skill `qwen-tools` en la
raiz del repo. Ahora cada script lleva el prefijo de su skill en la ruta canonical:

```
py "<skills>/qwen-web-search/scripts/buscar_web.py" --query "..." --json
```

El contador de presupuesto diario es un unico fichero compartido `skills/.qwen_uso_diario.json`
(lo escriben `buscar_web.py`, `buscar_imagen.py` e `extraer_web.py`). **No se incluye en el
repo**: es estado de runtime y esta en `.gitignore`. Se recrea solo al primer uso.

## Keys y bases

- **Token Plan `sk-sp-*`**: uso interactivo, region Singapur, consumo en Credits. Rige una
  **allowlist de nombres de modelo exact-string** — cualquier otro nombre responde
  `Model not exist`. Base que responde hoy (200 verificada 2026-11-09):
  `https://token-plan.maas.qwencloudapi.com/...` (Responses `compatible-mode/v1`, REST/WS
  `api/v1` y `api-ws/v1`). Los USD de la tabla son referencia de costo relativo.
- **Pay-as-you-go `sk-*` / `sk-ws-*`**: con saldo, para lotes y produccion. Requerido para
  `qwen-mcp` (ver trampa-200 abajo).
- **Resolucion automatica**: el script busca la key en `DASHSCOPE_API_KEY`, luego
  `ANTHROPIC_AUTH_TOKEN`, luego `~/.local/share/opencode/auth.json` (providers
  `alibaba-token-plan` / `-cn`); `--base-url` manda sobre todo.
- **Nunca hardcodear ni imprimir la key** (ni en stdout, stderr, `--out` ni en el JSON de
  error). Sin key alguna, el script sale con exit 2 y la instruccion de crear una en
  `https://home.qwencloud.com/api-keys`.

**Contrato comun de scripts:** un unico JSON por stdout (diagnosticos por stderr); exit
`0` OK · `1` API/red/generacion · `2` configuracion/uso · `3` presupuesto diario agotado
(sin HTTP, definitivo por el dia).

## Verificacion

Campana F2-GATE 2026-11-09: **14 tests, 0 FAIL, PASS** (~$0.62 de referencia, todo en
Credits). Hallazgos vivos confirmados con la base Token Plan documentada (gano en las 7
llamadas que la usaron; la base legacy jamas hizo falta):

- Las 10 skills pasan su smoke test con exit 0 + `ok:true` + evidencia.
- `qwen-video` — `wan3.0-video` **SI esta en Token Plan** con `sk-sp-` (duration `-1`
  smart, ratio `adaptive` -> 16:9, 30 fps, MP4 descargado). Corregido respecto a la doc vieja.
- `qwen-audio` — via `--http` (TTS `SpeechSynthesizer`) 200 con `sk-sp-`; ASR acepta
  `language_hints=["es"]` sin 400.
- `qwen-mcp` — **trampa-200**: con `sk-sp-` la tool `mcp` se ACEPTA (HTTP 200) pero queda
  SILENCIADA (`mcp_calls: []`, ~109 input tokens): las herramientas del server nunca se
  inyectan. Usar key pay-as-you-go para MCP real.

### Comandos de humo (1 por skill, rutas genericas)

```
py "<skills>/qwen-web-search/scripts/buscar_web.py"        --query "clima en Madrid hoy" --json
py "<skills>/qwen-image-search/scripts/buscar_imagen.py"   --query "gato siames" --json
py "<skills>/qwen-web-extractor/scripts/extraer_web.py"     --url "https://example.com" --prompt "resume" --json
py "<skills>/qwen-code-interpreter/scripts/ejecutar_codigo.py" --prompt "calcula factorial(20)" --json
py "<skills>/qwen-pdf/scripts/leer_pdf.py"                 --file informe.pdf --json
py "<skills>/qwen-mcp/scripts/consultar_mcp.py"            --server-url "<URL-SSE>" --label fetch --prompt "..."   # key pay-as-you-go
py "<skills>/qwen-function-calling/scripts/plantilla_function_calling.py" --json
py "<skills>/qwen-imagen/scripts/generar_imagen.py"        --prompt "un panda astronauta" --output panda.png
py "<skills>/qwen-video/scripts/generar_video.py"          --prompt "ola rompiendo en la orilla" --output ola.mp4 --resolution 480P --duration 3
py "<skills>/qwen-audio/scripts/sintetizar_voz.py"         --text "hola, prueba" --output voz.mp3
py "<skills>/qwen-audio/scripts/transcribir_audio.py"      --audio voz.mp3 --json
```

Sustituye `<skills>` por tu directorio de skills (p. ej. `%USERPROFILE%\.config\opencode\skills`).

## Documentacion oficial (QwenCloud — Tool calling)

1. Function calling — https://docs.qwencloud.com/developer-guides/tool-calling/function-calling
2. Web search — https://docs.qwencloud.com/developer-guides/tool-calling/web-search
3. Web extractor — https://docs.qwencloud.com/developer-guides/tool-calling/web-scraping
4. Code interpreter — https://docs.qwencloud.com/developer-guides/tool-calling/code-interpreter
5. Image search — https://docs.qwencloud.com/developer-guides/tool-calling/image-search
6. Connect to MCP servers — https://docs.qwencloud.com/developer-guides/tool-calling/mcp
7. PDF understanding — https://docs.qwencloud.com/developer-guides/tool-calling/pdf-understanding

Issues y PRs bienvenidos.
