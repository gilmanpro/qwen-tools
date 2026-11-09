---
name: qwen-imagen
description: >
  Genera y edita imagenes con QwenCloud (Qwen-Image / Wan2.7, REST sincrona multimodal-generation,
  key sk-sp- del Token Plan resuelta sola desde auth.json): posters, banners, infografias, menus,
  storyboards, ilustracion con tipografia renderizada (12 idiomas), texto/fuente exactos en la
  imagen, ilustracion realista/4K, edicion por instruccion con 1-3 imagenes de entrada, bocetos
  baratos. Usa SIEMPRE que el usuario pida generar o editar una imagen con IA de Qwen, un poster
  o un banner, aunque no nombre la herramienta. Elige el modelo solo (NUNCA pregunta), descarga los
  PNG automaticamente (las URLs del resultado EXPIRAN en 24 h) y factura solo las imagenes
  exitosas (~$0.03-0.075 por imagen de referencia). NO para: generar VIDEO → skill qwen-video;
  buscar fotos YA existentes en la web o imagen inversa → skill qwen-image-search; montar una
  UI/pagina web → dev-stack.
license: MIT
metadata:
  version: "3.0"
  split-de: "qwen-tools v2.0"
  api_base_rest: "https://token-plan.maas.qwencloudapi.com/api/v1"
---

# QWEN-IMAGEN — generar y editar imagenes con Qwen-Image / Wan2.7

Un dominio, un script: `scripts\generar_imagen.py` (solo stdlib, sin `pip install`). REST
**sincrona** (`POST {base}/services/aigc/multimodal-generation/generation`); el script llama la
API y **descarga los PNG automaticamente — las URLs del resultado EXPIRAN EN 24 h**, nunca dejar
solo la URL como entregable. Con `--n > 1` guarda `nombre_1.png`, `nombre_2.png`...

Invocacion canonical:

```
py "%USERPROFILE%\.config\opencode\skills\qwen-imagen\scripts\generar_imagen.py" --prompt "A red panda astronaut on the moon, cinematic lighting, ultra detailed" --output panda.png
```

## NUNCA PREGUNTAR QUE MODELO USAR (aplica a sub-agentes tambien)

Elegir automaticamente. La eleccion **SE ANULA si el usuario da una pista**: nombra un modelo →
ese; pide ahorro ("barato", "economico", "prueba rapida") → el mas economico; pide "realista" /
"4K" / color de marca exacto → el especializado. **Reportar SIEMPRE** en la respuesta final que
modelo se uso y por que (1 linea) con su costo de referencia.

| Caso | Modelo (Token Plan) | Costo ref. |
|---|---|---|
| Default: texto renderizado, posters, banners, layouts densos (menus, periodicos, storyboards), ilustracion con tipografia (12 idiomas, hasta 6 variantes) | `qwen-image-3.0-pro` | $0.04 (1K) / $0.075 (2K) |
| "realista", retrato fotografico, 4K (4096x4096), color de marca preciso, sets coherentes | `wan2.7-image-pro` | $0.075 |
| "ahorra"/barato, volumen, bocetos, pruebas (hasta 2K, sets de 12, paleta, 9 referencias en edicion) | `wan2.7-image` | $0.03 |

Allowlist Token Plan (`sk-sp-*`): SOLO esos 3 de imagen; cualquier otro nombre → `Model not
exist` (no existen variantes legacy `max`/`plus` en Token Plan). `wan3.0-video` es VIDEO
(skill `qwen-video`), no imagen.

## KEY Y BASES — resolucion automatica (familia B, REST)

**Nunca imprimir la key ni el body** (stdout, stderr ni `--out`). Sin ninguna key → exit 2 con
instruccion (crear key en https://home.qwencloud.com/api-keys). Precedencia: 1.
`DASHSCOPE_API_KEY`, 2. `ANTHROPIC_AUTH_TOKEN`, 3. `~/.local/share/opencode/auth.json` (providers
`alibaba-token-plan` / `alibaba-token-plan-cn`). Host por prefijo de key (o `--base-url` que manda
sobre todo):

| Key | Base REST |
|---|---|
| `sk-sp-*` (Token Plan) | `https://token-plan.maas.qwencloudapi.com/api/v1` — **las bases Token Plan NO llevan region ID** (Token Plan solo existe en Singapur) |
| `sk-*` / `sk-ws-*` (pay-as-you-go) | `https://ap-southeast-1.maas.qwencloudapi.com/api/v1` — forma con region ID segun doc regions (`developer-guides/getting-started/regions`); la forma pelada `maas.qwencloudapi.com` es el alias equivalente de Singapur |

El consumo Token Plan se liquida en **Credits**; los USD son referencia de costo relativo
(verificados 2026-10-02 en www.qwencloud.com/models y docs.qwencloud.com — pueden cambiar). Key
`sk-sp-*` orientada a uso interactivo; lotes/produccion → key pay-as-you-go con saldo.

## OPCIONES DEL SCRIPT

`--prompt` / `--prompt-file` (recomendado en Windows por quoting; uno obligatorio), `--output`
obligatorio, `--model`, `--size W*H`, `--n 1-6`, `--negative "..."`, `--seed N`, `--no-extend`,
`--extend-mode direct|agent`, `--no-thinking`, `--watermark`, `--base-url`, `--timeout` (default
300 s), `--json` no aplica: el script ya imprime UN JSON de exito (`ok`, `request_id`, `model`,
`base`, `dimensiones`, `imagenes`, `segundos`).

Parametros clave (los enviar SOLO el camino documentado; detalle literal en
`references\api-qwen-image.md`):

- Costo = precio x imagenes **exitosas** → probar con `--n 1` primero; las fallidas NO se facturan.
- `prompt_extend` default **true** (+3-4 s en prompts cortos; reescritura del prompt);
  `prompt_extend_mode` `agent` = SOLO serie 3.0 y SOLO text-to-image (en edicion → 400).
- `enable_thinking` (solo serie 3.0, default true, **requiere prompt_extend=true**; `--no-thinking`
  lo apaga) → +calidad +tiempo.
- `negative_prompt` max 500 chars (se trunca) — **NO soportado por wan2.7-image(-pro)**.
- `watermark` default **false** (la marca "Qwen-Image" va en esquina inferior derecha si la pides
  con `--watermark`).
- `seed` 0-2147483647: misma seed ≈ resultados consistentes (no identicos).

## TAMAÑOS Y RATIOS (separado por MODELO)

`--size "ancho*alto"`; **omitido = el modelo lo recomienda segun el prompt**. El rango antiguo
(512x512–2048x2048 px de AREA) era del dominio `qwen-image-3.0-pro` y **NO aplica igual a wan2.7**:

| Modelo | Rango de `size` |
|---|---|
| `qwen-image-3.0-pro` (+ serie 3.0/2.0) | AREA TOTAL entre `512*512` (262.144 px) y `2048*2048` (4.194.304 px), ratio 1:8–8:1; lados fuera de 512-2048 son validos si area y ratio se cumplen (p.ej. `2688*1536`) |
| `wan2.7-image` | **area 589824–16777216 px** — `512*512` (262144 px) se RECHAZA con HTTP 400 (F2c 2026-11-09); minimo practico `768*768` (589824 px) |
| `wan2.7-image-pro` | mismo rango documentado para `wan2.7-image` (589824–16777216 px) **salvo verificacion** (sin evidencia viva propia) |

Referencias practicas (1K / 2K): cuadrado 1280x1280 / 2048x2048; banner 16:9 1696x960 / 2688x1536;
vertical 9:16 960x1696 / 1536x2688; 4:3 1472x1104 / 2368x1728; 3:4 1104x1472 / 1728x2368. Tier de
facturacion: 1K hasta 2.250.000 px, de ahi 2K.

Prompt en **ingles**: sujeto + accion/pose + entorno + iluminacion + estilo/medio + paleta +
calidad + texto literal entre comillas. Serie 3.0 acepta ~4500 tokens → composicion por zonas
("Left upper: ... Center title: ..."). Patron oficial: sujeto → detalles por zonas → iluminacion →
estilo/medio → texto entre comillas → calidad.

## EDICION (pro / wan2.7 / serie 3.0)

Input: 1-3 imagenes (serie 3.0; wan2.7 hasta 9) + instruccion en el mismo `content` del mensaje
`user` (`{"image": URL|data URI}`s + `{"text": "The girl in Image 1 wears the dress from Image 2..."}`
— el orden importa: Image 1 = primera). Formatos de entrada JPG/PNG/BMP/TIFF/WEBP/GIF (primera
frame), lados 1-8000 px (ideal 384-2048), ratio max 10:1, <=10 MB por imagen; salida PNG. El body
exacto esta documentado LITERAL en `references\api-qwen-image.md` (fuente:
`docs.qwencloud.com/developer-guides/image-generation/image-editing`) — **NO inventarlo**.
Edicion factura tambien las imagenes de entrada (fee = precio x imagenes_input + precio x
imagenes_output).

## REFERENCIAS REALES DE LA WEB (autorizado)

Buscar logos/fotos/paletas de marca (webfetch, Wikimedia, fuentes libres), descargar al
**directorio de trabajo** (NO dentro de la skill) y usarlas como input de edicion o para extraer
hex/proporciones reales hacia el prompt. Preferir licencia libre; imagenes de marcas reales pueden
disparar `DataInspectionFailed` → describir el estilo en el prompt en vez de enviar la imagen;
NUNCA incrustar logos de terceros en contenido que parezca oficial sin autorizacion explicita.

## ERRORES (dominio imagen)

| Situacion | Accion |
|---|---|
| HTTP 429 / `Throttling*` | rate limit (util: pro 5 RPM / 10 concurrentes): esperar y reintentar; el script NO reintenta imagen — reducir ritmo |
| HTTP 401 / `InvalidApiKey` | key invalida o key↔host incorrectos (`sk-sp-*` ⇒ host `token-plan.maas.qwencloudapi.com`). Detenerse |
| `Model not exist` | modelo fuera de la allowlist del Token Plan (usar qwen-image-3.0-pro / wan2.7-image / wan2.7-image-pro) |
| `DataInspectionFailed` | moderacion (prompt, negative o imagen de entrada) → reescribir prompt / cambiar imagen |
| HTTP 400 `InvalidParameter` | rango invalido: `size` con area fuera de 512\*512–2048\*2048 px (serie 3.0; wan2.7: area >= 589.824 px — ver fila propia), n 1-6, negative <=500; `prompt_extend_mode:agent` en edicion; modelo wan2.7 + `negative_prompt` |
| HTTP 400 `InvalidParameter` (wan2.7 `size` chico) | literal del server: `Total pixels (262144) must be between 589824 and 16777216` — `512*512` NO vale en wan2.7-image; usar `>=768*768` (evidencia F2c 2026-11-09) |
| Download fail tras SUCCEEDED | la URL expira en 24 h → reintentar generacion |
| `Arrearage` | saldo pendiente (pay-as-you-go): regularizar pago |

**Exit codes**: `0` OK · `1` error de API/descarga · `2` configuracion/uso (falta key o prompt,
`--n`/`--size` invalidos). El presupuesto diario compartido (30 busquedas web+imagen) NO aplica
aqui: la generacion de imagen no consume ese contador.

## ARCHIVOS

```
qwen-imagen/
├── SKILL.md
├── README.md
├── scripts/generar_imagen.py          # POST sincrono multimodal-generation + descarga PNG
└── references/api-qwen-image.md       # endpoint, bodies literales (t2i y edicion), parametros, errores
```

Referencias a un solo nivel: leer la reference SOLO cuando el body de esta skill no baste
(detalle de API, ejemplos literales, casos raros).
