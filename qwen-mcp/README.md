# qwen-mcp

Usa un **servidor MCP externo** (Model Context Protocol, protocolo SSE) desde los modelos
QwenCloud via la tool `{"type":"mcp"}` de la Responses API. La URL SSE del endpoint la
aporta SIEMPRE el usuario — el script nunca improvisa endpoints. Ojo: con key Token Plan
(`sk-sp-`) la tool se ACEPTA (200) pero se SILENCIA (`mcp_calls:[]`, input ~109 tok) — es una
TRAMPA 200; para MCP real usar key pay-as-you-go (`sk-*` / `sk-ws-*`). Ver CAUCION en `SKILL.md`.

## Ejemplo (ruta canonical)

```
py "%USERPROFILE%\.config\opencode\skills\qwen-mcp\scripts\consultar_mcp.py" --server-url "https://mcp.api-inference.modelscope.net/XXX/sse" --prompt "resume https://example.com" --json
```

Script solo-stdlib (`py` de Windows, sin `pip install`). Key y headers nunca se imprimen.
Detalle API: `references\api-mcp.md`.
