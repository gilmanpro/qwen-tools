# api-pdf.md — PDF understanding en QwenCloud (detalle API)

Fuente: docs.qwencloud.com/developer-guides/tool-calling/pdf-understanding (fetcheado
2026-11-09). Leer SOLO cuando el body de SKILL.md no baste.

## Soporte y vias

| Via | ¿Soporta PDF? | Notas |
|---|---|---|
| **Chat Completions** (`/compatible-mode/v1/chat/completions`) | SI | recomendada; el script `leer_pdf.py` usa esta |
| **DashScope native** | SI | protocolo alternativo: el elemento de content lleva `file_url`/`file_data` directos (sin wrapper `type:"file"` de OpenAI); ver pestana "DashScope" de la doc oficial antes de reimplementar |
| **Responses API** (`/responses`) | **NO** | ⚠️ TRAMPA: devuelve **HTTP 200** con respuesta del modelo **sin haber recibido el archivo** — sin error ni senal. Nunca pasar PDFs por Responses |

Modelos soportados (doc oficial): `qwen3.8-max`, `qwen3.8-max-0902`, `qwen3.8-flash`.

## Bases por region/key (compatible-mode)

- Pay-as-you-go Singapore (doc oficial): `https://ap-southeast-1.maas.qwencloudapi.com/compatible-mode/v1`
  — "API keys are region-specific; replace ap-southeast-1 for another region".
- Token Plan (`sk-sp-*`): cadena de SKILL.md — primero la oficial documentada
  `https://token-plan.maas.qwencloudapi.com/compatible-mode/v1` (sin region ID), luego la
  legacy `https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1`
  (esta ultima NO aparece en la doc; fallback).

## Body OpenAI-compatible (URL) — literal de la doc

SDK Python (lo que hace el script en raw HTTP):

```python
completion = client.chat.completions.create(
    model="qwen3.8-max",
    messages=[
        {
            "role": "user",
            "content": [
                {
                    "type": "file",
                    "file": {
                        "file_url": "https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20260616/qmycjl/1506.02640v5.pdf"
                    }
                },
                {"type": "text", "text": "Summarize this PDF document"}
            ]
        }
    ],
    stream=True,
    stream_options={"include_usage": True},
    extra_body={"include_tool_usage": True}
)
```

Equivalente raw HTTP (curl) — ojo: `include_tool_usage` va **TOP-LEVEL**, NO dentro de
`extra_body` (eso es solo del SDK) ni de `stream_options`:

```bash
curl -X POST "https://ap-southeast-1.maas.qwencloudapi.com/compatible-mode/v1/chat/completions" \
  -H "Authorization: Bearer $DASHSCOPE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3.8-max",
    "messages": [{
      "role": "user",
      "content": [
        {"type": "file", "file": {"file_url": "https://.../documento.pdf"}},
        {"type": "text", "text": "Resume este documento"}
      ]
    }],
    "stream": true,
    "stream_options": {"include_usage": true},
    "include_tool_usage": true
  }'
```

## Body con base64 (file_data) — literal de la doc

```python
with open("report.pdf", "rb") as f:
    pdf_base64 = base64.b64encode(f.read()).decode("utf-8")

completion = client.chat.completions.create(
    model="qwen3.8-max",
    messages=[
        {
            "role": "user",
            "content": [
                {
                    "type": "file",
                    "file": {
                        "file_data": f"data:application/pdf;base64,{pdf_base64}",
                        "filename": "report.pdf"
                    }
                },
                {"type": "text", "text": "What are the key findings in this report?"}
            ]
        }
    ]
)
```

- `filename` es **OBLIGATORIO** cuando se usa `file_data`.
- Base64 infla ~1/3: 150 MB → ~200 MB de cuerpo → excede el limite; para archivos
  grandes pasar por URL.

## Parametros del elemento file (OpenAI-compatible)

| Parametro | Tipo | Obligatorio | Description |
|---|---|---|---|
| `file_url` | string | uno de los dos | URL de descarga del PDF. Mutualmente exclusivo con `file_data` |
| `file_data` | string | uno de los dos | `data:application/pdf;base64,xxx`. Exclusivo con `file_url` |
| `filename` | string | condicional | Requerido con `file_data` |
| `file_format` | string | no | Solo `pdf` (default `pdf`) |

La URL del campo acepta **un solo string** — una lista de URLs NO esta soportada.

## Limites y latencia

| Item | Valor |
|---|---|
| Tamano max | 150 MB |
| Paginas max | 256 |
| First-token | hasta **300 s** → usar stream (recomendacion explicita de la doc) |

## Billing

1. **Input tokens**: texto e imagenes parseados del PDF cuentan como tokens de input al
   precio estandar del modelo.
2. **Fee `document_parsing`** (medidor pdf) por pagina parseada:
   China North 2 (Beijing) **$0.003/pagina** · Singapore **$0.0033/pagina**.
3. ⚠️ **Token Plan**: el fee `document_parsing` no esta documentado para `sk-sp-` —
   verificar en账单; con TP riesgo de facturacion PAYG del fee (ver SKILL.md).

Conteo de paginas en la respuesta (requiere `include_tool_usage:true`):

```json
{
  "usage": {
    "x_tools": {
      "pdf_page_parser": {
        "count": 10,
        "strategy": "normal"
      }
    }
  }
}
```

(Las dos vias difieren ligeramente en como exponen `usage`: via SDK por `extra_body`, via
raw HTTP top-level; la via DashScope native lo trae a su manera — ver pestana DashScope.)

## Parseo del stream (lo que hace leer_pdf.py)

- Lineas SSE `data: {json}`; el payload final `[DONE]` cierra.
- El texto llega en `choices[].delta.content` (acumular concatenando).
- El chunk final trae `choices: []` y `usage` con `prompt_tokens`/`completion_tokens`/
  `total_tokens` y, si se pidio, `x_tools.pdf_page_parser.count`.

## Errores

Tabla de errores generales: /api-reference/preparation/error-messages (doc oficial).
Los patrones que devuelve esta API aterrizan en la tabla ERRORES de SKILL.md
(400 por tamano/paginas, 401 key↔host, 429 rate limit, `Model not exist` fuera de
allowlist).
