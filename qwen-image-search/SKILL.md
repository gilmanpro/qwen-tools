---
name: qwen-image-search
description: >
  Busqueda de IMAGENES con QwenCloud via Responses API (key sk-sp- del Token Plan
  resuelta sola): dos tools — web_search_image (texto → fotos de la web, el modelo
  responde con analisis) e image_search (imagen inversa: URL publica, data URI o ruta
  local → imagenes similares). Usa SIEMPRE que el usuario pida buscar fotos/imagenes
  con IA de Qwen o identificar "que es esta imagen" con similaridad visual, aunque no
  nombre la herramienta. Max 100 resultados por busqueda; presupuesto diario compartido
  de 30 busquedas web+imagen (exit 3 al agotarse); pre-validacion gratuita de --image
  antes de gastar Credits. NO para: generar/editar una imagen nueva → skill qwen-imagen;
  buscar TEXTO/noticias → skill qwen-web-search.
license: MIT
metadata:
  version: "3.0"
  split-de: "qwen-tools v2.0"
  api_base_responses: "https://token-plan.maas.qwencloudapi.com/compatible-mode/v1"
---

# QWEN-IMAGE-SEARCH — fotos por texto e imagen inversa (Responses API)

Dos tools server-side sobre la **Responses API**: `web_search_image` (texto → imagenes) e
`image_search` (imagen → imagenes similares). Cada busqueda devuelve un array JSON
`[{index,title,url}, ...]` (max **100** resultados, lo decide el modelo) **mas un analisis
del modelo** sobre ellas. Un script solo-stdlib cubre ambos modos: `scripts\buscar_imagen.py`.

**REGLA DURA DEL HARNESS**: `web_search_image` e `image_search` **SOLO existen en la
Responses API** (`POST {base}/responses`); Chat Completions NO dispara el harness. Ademas
**solo estan disponibles en las regiones Singapur y China North 2 (Beijing)** — y el
**Token Plan opera en region Singapur**, o sea que con key `sk-sp-*` la restriccion se
cumple **de fabrica** (no es una limitacion practica para esta skill).

## DISPATCH (leer primero)

| Que pide el usuario | Modo | Flags |
|---|---|---|
| Buscar fotos por descripcion | texto → imagen | `--query "gato siames"` (tool `web_search_image`) |
| "Que es esta imagen" / imagenes similares | busqueda inversa | `--image URL\|data-URI\|ruta-local [--query contexto]` (tool `image_search`) |
| GENERAR una imagen nueva (no buscar) | — | skill `qwen-imagen` |

## COMO INVOCAR (ruta canonical)

```
:: texto -> fotos
py "%USERPROFILE%\.config\opencode\skills\qwen-image-search\scripts\buscar_imagen.py" --query "gato siames" --json
:: busqueda inversa (URL publica, data URI o ruta local — el script la convierte a data URI)
py "%USERPROFILE%\.config\opencode\skills\qwen-image-search\scripts\buscar_imagen.py" --image "https://picsum.photos/id/237/400/400" --query "perro raza" --json
```

Modelo default: `qwen3.8-flash` (funciona, rendimiento algo menor que los recomendados;
`qwen3.8-max` sube calidad). Flags: `--query`, `--image`, `--model`, `--base-url`,
`--timeout` (180 s), `--json`, `--n` (recorte client-side de `sources[]`, default 5;
max doc 100; 0 = todos), `--analysis full|short|no` (texto del modelo, clave `answer`),
`--max-uses` (param no listado: reintento automatico sin el campo si 400),
`--max-searches-dia` (default 30; 0 = sin limite), `--saltar-validacion`.

## CUANDO ACTIVAR (politica de ahorro — default OFF)

Cada busqueda de imagen **cuesta Credits** y los resultados recuperados **suben los input
tokens**. No la actives por iniciativa propia: vias gratuitas primero. El `exit 3` es
definitivo por el dia. Generar la imagen directamente (skill `qwen-imagen`) suele ser mas
barato que buscar 30 fotos.

## KEY Y BASES — resolucion automatica (Familia A — Responses API)

**Nunca imprimir la key ni el body** (stdout, stderr ni `--out`). Sin ninguna key → exit 2
con instruccion (crear key en https://home.qwencloud.com/api-keys).

1. `~/.local/share/opencode/auth.json` → providers `alibaba-token-plan` / `-cn` (key
   `sk-sp-*`) → **cadena de bases** probada en orden hasta responder en `/responses` sin
   401/404/405 (el JSON registra la que funciono en `base`):

| Base candidata | Orden | Estado / fuente |
|---|---|---|
| `https://token-plan.maas.qwencloudapi.com/compatible-mode/v1` | 1 | **documentada del Token Plan** (fuente: docs regions/quickstart TP; las bases TP NO llevan region ID) — **200 verificada en vivo 2026-11-09** (evidencia `.tmp\qwen-split\tests\`; 7/7 llamadas ganaron esta base) |
| `https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1` | 2 | legacy — **fallback, no necesaria desde 2026-11-09** (200 empirico 2026-10-07; NO aparece en la doc) |
| `https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1` | 3 | empirica: 401 con la key sk-sp- actual (queda para otras keys/workspace) |

2. `ANTHROPIC_AUTH_TOKEN` si empieza por `sk-sp-` → misma cadena. 3. `DASHSCOPE_API_KEY`
(pay-as-you-go `sk-*`) → `https://maas.qwencloudapi.com/compatible-mode/v1` (region de la
key: solo sirve si es Singapur o Beijing-N2). 4. `--base-url` manda sobre todo.

**Allowlist Token Plan** (`sk-sp-*`): cualquier otro modelo → `Model not exist`. Consumo
en **Credits**; USD = referencia. Key `sk-sp-*` para uso **interactivo**.

## PRE-VALIDACION GRATUITA DE `--image` (no consume Credits)

Orden en `main()`: argumentos → presupuesto (exit 3) → **pre-validacion (exit 2)** → key →
API. URL `http(s)`: HEAD (15 s) y si hace falta GET `Range: bytes=0-511`; rechaza 4xx/5xx,
content-type no `image/*` o magic bytes no PNG/JPEG/GIF/WEBP/BMP (`motivo: estado-http` /
`no-es-imagen` / `magic-no-coincide`); ambiguo (401/403/429 o sin respuesta) →
`url-no-verificable` (el hint invita a `--saltar-validacion` SOLO si el usuario confirma
que la URL funciona). data URI: MIME `image/*` + decodificacion + firma. Ruta local:
existe, es archivo, <=20 MB y firma en los primeros 12 bytes. Rechazo: UN unico JSON
`{"ok":false,"error":"imagen_no_valida","motivo":"...","hint":"..."}` exit 2, **sin HTTP a
la API paga y sin sumar al contador**. `--saltar-validacion` omite SOLO este paso.

## PRESUPUESTO DIARIO — contador compartido

Fichero UNICO `skills\.qwen_uso_diario.json` (resuelto por los scripts como
`parents[2]`; dueno de ninguna skill), formato
`{"fecha":"YYYY-MM-DD","web":N,"imagen":N,"extractor":N}`. Limite combinado **web+imagen
>= 30/dia** (`--max-searches-dia`) → exit 3 con `budget_exceeded:true` **sin lanzar
HTTP**. Bucket `imagen`: suma `usage.x_tools.web_search_image.count` +
`image_search.count` tras exito; fallo de red NO suma; corrupto = 0 y se recrea;
escritura atomica tmp+rename; reset = borrar el archivo (la fecha reinicia sola). El
bucket `extractor` es informativo (no consume el limite).

## CONTRATO DE SALIDA (UN JSON unico en stdout; diagnosticos por stderr)

```json
{ "ok": true, "query": "…", "answer": "analisis del modelo",
  "sources": [{"index": 1, "title": "…", "url": "https://…"}],
  "searches": ["query real lanzada"], "usage": {"input_tokens": 2753,
  "output_tokens": 181, "x_tools": {"image_search": {"count": 1}}},
  "seconds": 12.4, "mode": "image_search", "base": "https://token-plan.maas.qwencloudapi.com/compatible-mode/v1" }
```

`mode`: `web_search_image` (texto) | `image_search` (inversa). En modo inverso `searches`
puede venir vacio. Error: `ok:false` con `http_status`, `error`, `attempted` (bases
probadas). `sources: []` con `ok:true` es valido: el modelo decidio no disparar la tool
("the model decides when to search") — decirlo y proponer imagen/consulta mas concreta.
La imagen demasiado pequena (>10 px de lado minimo exigido) o una URL que el servidor no
puede descargar devuelven 400 `InvalidParameter` ("Download multimodal file timed out").

## FEES (list price — Token Plan lo cobra en Credits)

| Tool | Fee por 1.000 llamadas | Notas |
|---|---|---|
| `web_search_image` | **$8.00 Singapur** · $6.881 Beijing-N2 | Max 100 resultados/busqueda; SOLO Responses; SOLO regiones SG+Beijing (TP = SG de fabrica); resultados suben input tokens |
| `image_search` | **$8.00 Singapur** · $6.881 Beijing-N2 | Idem; la URL/data URI debe ser legible por el servidor |

## ERRORES

| Situacion | Accion |
|---|---|
| exit 2 `imagen_no_valida` | pre-validacion rechazo (motivo en el JSON): URL rota/no-imagen/firma invalida. Corregir input o, si el usuario confirma que es valida, `--saltar-validacion` |
| HTTP 400 `InvalidParameter` / "Download multimodal file timed out" | imagen muy pequena o URL no descargable por el servidor: probar otra URL o data URI local |
| HTTP 429 / `Throttling*` | el script reintenta 2x (5 s/10 s); persiste → esperar 1 min, reducir ritmo |
| HTTP 401 / `InvalidApiKey` | key invalida o key↔host (`sk-sp-*` ⇒ hosts token-plan). Detenerse |
| `Model not exist` | modelo fuera de la allowlist del Token Plan |
| exit 3 `budget_exceeded` | presupuesto web+imagen agotado hoy: NO reintentar (reset: borrar `skills\.qwen_uso_diario.json`) |
| `sources: []` con `ok:true` | el modelo decidio no buscar: proponer consulta/imagen mas concreta |

## ARCHIVOS

```
qwen-image-search/
├── SKILL.md
├── README.md
├── scripts/
│   └── buscar_imagen.py         # web_search_image + image_search (stdlib, contador parents[2])
└── references/
    └── api-image-search.md      # detalle API: bodies, items, formatos, FAQ, fees
```

Leer la reference SOLO cuando el cuerpo de esta skill no baste. Generar imagen →
`qwen-imagen`; buscar texto → `qwen-web-search`.
