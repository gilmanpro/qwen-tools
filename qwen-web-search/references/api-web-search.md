# QwenCloud — Web search (Responses API, tool `web_search`)

Fuentes (consultadas 2026-11-09, docs oficiales en vivo + pruebas propias):
- https://docs.qwencloud.com/developer-guides/tool-calling/web-search
- https://docs.qwencloud.com/developer-guides/getting-started/regions
- Pruebas reales 2026-10-07 (smoke tests del script original).

**REGLA DURA DEL HARNESS**: las tools del proveedor (`web_search`, `web_search_image`,
`image_search`, `web_extractor`, `code_interpreter`) SOLO se invocan a traves de la
**Responses API** (`POST {base}/responses`). En Chat Completions el `tools[]` con estas
types NO dispara el harness. La via Chat usa `enable_search` (otro mecanismo; NO devuelve
fuentes citables — la doc lo desaconseja para citas).

## Bases URL (autenticacion)

Precedencia de resolucion key → base (`buscar_web.py`):

1. `~/.local/share/opencode/auth.json` provider `alibaba-token-plan` / `alibaba-token-plan-cn`
   con key `sk-sp-*` → **cadena TP** (orden actual; gana la primera que responda en
   `/responses` sin 401/404/405; el JSON registra `base` = la que respondio):

| # | Base | Estado / fuente |
|---|---|---|
| 1 | `https://token-plan.maas.qwencloudapi.com/compatible-mode/v1` | **documentada del Token Plan** (fuente: docs regions/quickstart TP). Las bases TP NO llevan region ID — **200 verificada en vivo 2026-11-09** (evidencia `.tmp\qwen-split\tests\`; 7/7 llamadas ganaron esta base) |
| 2 | `https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1` | **legacy — fallback, no necesaria desde 2026-11-09**: 200 empirico 2026-10-07 (era la base "VERIFICADA 200" de la skill v2.0); NO aparece en la doc |
| 3 | `https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1` | empirica: 401 `InvalidApiKey` con la key sk-sp- del workspace ap-southeast-1; queda para otras keys/workspace |

   (Retirada de la cadena: `https://ws-<ID-workspace>.ap-southeast-1.maas.aliyuncs.com/api/v1`
   — 404 verificado 2026-10-07 en /responses y /chat/completions y sin respaldo documental.)
2. `ANTHROPIC_AUTH_TOKEN` si empieza por `sk-sp-` → misma cadena TP.
3. `DASHSCOPE_API_KEY` (pay-as-you-go, prefijo `sk-`/`sk-ws-`) →
   `https://maas.qwencloudapi.com/compatible-mode/v1`.
4. `--base-url` manda sobre todo (una sola base, sin cadena).

Sin ninguna key → exit 2. **Nunca** imprimir la key. **Token Plan = region Singapur**: las
filas de fees/modelos de la doc que aplican a TP son las de Singapur.

## Estructura de la respuesta (observada en pruebas reales)

`output` es un array con items intercalados:

- `type: "reasoning"` — trazas de pensamiento (no se usan). En Responses,
  `enable_thinking` esta deprecated: se controla con `reasoning.effort`.
- `type: "web_search_call"` — accion de busqueda. Claves:
  - `action.query` (string) y/o `action.queries` (lista): consultas lanzadas (puede haber
    varios items = retrieval agentico multi-turno).
  - `action.sources`: lista de `{type, url}` — **puede faltar o venir vacia** (tolerar).
- `type: "message"` — respuesta final: `content` = partes; la util es
  `{"type":"output_text","text":...}`.

`usage` incluye `x_tools` (p. ej. `{"web_search": {"count": 2}}`) y `x_details`. Un
`count > 1` o varios `*_call` = retrieval agentico multi-turno decidido por el modelo.
`status: "completed"` con `error: null` en exito. Errores reales: HTTP 4xx con
`{"error": {"code","type","message"}}`.

## Body literal (lo que envia el script)

```json
POST {base}/responses
{
  "model": "qwen3.8-flash",
  "input": "clima en Madrid hoy",
  "tools": [{"type": "web_search"}]
}
```

En Responses **no** existen `enable_source`, `enable_citation`, `citation_format` ni
`search_strategy`: se ignoran silenciosamente. Las fuentes salen en
`web_search_call.action.sources` **sin marcadores [1]** (para marcadores, via DashScope).

## Estrategias `search_strategy` (vias Chat Completions / DashScope — referencial)

`extra_body={"enable_search": True, "search_options": {"search_strategy": "..."}}`:

| Estrategia | Que hace | Soporte |
|---|---|---|
| `turbo` (default) | equilibrio velocidad/calidad | todas las series con busqueda |
| `max` | multiples motores, resultados mas exhaustivos, mas lento | idem |
| `agent` | retrieval agentico multi-vuelta (N llamadas busqueda+modelo) | Qwen3.5/3.6/3.7 (incl. open-source; Omni solo `agent`). **Qwen3.8 NO soporta `agent` en la via multimodal** (turbo/max): retrieval agentico 3.8 = Responses API. Exige stream en endpoint de texto. Con agent solo se admite `enable_source:true` |
| `agent_max` | `agent` + lectura de paginas completas (web extractor) | **solo qwen3.7-max en modo thinking**; exige stream |

Via multimodal (`multimodal-generation`; Qwen3.8/3.7-flash/plus/3.6/3.5 series con input
imagen/video): **la busqueda exige `stream=True`** (else
`Non-streaming mode does not support Web Search`); llamarla por `text-generation` da
400 `url error, please check url`. Java: `enableSearch(true)` + `parameter("search_options", ...)`.

## Fuentes por via

| Via | Donde salen |
|---|---|
| Responses API | `output[].type=="web_search_call"` → `action.sources[].url` (sin [1]) |
| DashScope | `search_options.enable_source: true` → `search_info.search_results` (`index`/`title`/`url`, marcadores [n] en el texto) |
| Chat Completions compatible | sin fuentes citables |

## Modelos soportados (extracto doc 2026-11-09)

- **Qwen3.8**: qwen3.8-max, qwen3.8-max-0902, qwen3.8-flash, qwen3.8-2.4t-a95b, qwen3.8-27b
  (`agent` NO soportado; retrieval agentico → Responses).
- **Qwen3.7**: max (+preview/snapshots), plus, flash. **Qwen3.6**: plus, flash, 27b, 35b-a3b.
  **Qwen3.5**: plus, flash, open-source; Omni (qwen3.8-omni-flash, qwen3.5-omni-plus/flash
  y realtime): la estrategia queda fijada a `agent`.
- Terceros: deepseek-v4.1-flash(-1017), deepseek-v4-pro/-flash; glm-5.2 (solo Responses);
  kimi-k3 (solo Responses), kimi-k3.1-pro (Responses `web_search` + Anthropic `web_search`;
  NO Chat `enable_search`).
- Regiones con busqueda: Singapur, Beijing-N2, Frankfurt, HK, Tokyo, Virginia (Global para
  Frankfurt/HK/Tokyo). TP opera en **Singapur**.

## Billing (list price; promociones en www.qwencloud.com/models)

| Estrategia/Tool | Fee por 1.000 llamadas |
|---|---|
| `agent` (y Responses `web_search`, mismo tarifado) | **Singapur $10.00** · Beijing-N2/Frankfurt/HK/Tokyo/Virginia **$0.573411** |
| `agent_max` | busqueda = precio `agent`; web extractor gratis por tiempo limitado |

Ademas: el contenido web recuperado se anade al prompt → **aumenta los input tokens**
(precio estandar del modelo). **Token Plan**: todo se descuenta en **Credits**, no en
factura pay-as-you-go.

**FAQ de facturacion (doc)**: `count` (`usage.x_tools.web_search.count` en OpenAI-compat;
`usage.plugins.search.count` en DashScope — mismo valor) = intencion de busqueda detectada
en la etapa de deteccion; **no** significa que la recuperacion termino con exito y **no es
base de facturacion ni conciliacion** (sigue siendo !=0 con rate limit o sin resultados).
Reconciliar SOLO contra la factura/saldo de Credits.

## Rate limits (429)

Throttling → HTTP 429; el script reintenta 2 veces (esperas 5 s / 10 s, backoff) y lo
diagnostica por stderr. Policy TP ante 429: esperar ~1 min. Persiste → reducir ritmo.
