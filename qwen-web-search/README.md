# qwen-web-search

Busqueda web con fuentes citables usando la tool `web_search` de la **Responses API** de
QwenCloud (Token Plan o pay-as-you-go). Script Python solo-stdlib con contador diario
compartido (30 busquedas web+imagen/dia).

Ejemplo de invocacion (ruta canonical):

```
py "%USERPROFILE%\.config\opencode\skills\qwen-web-search\scripts\buscar_web.py" --query "clima en Madrid hoy" --json
```

Instrucciones completas, estrategias, fees y tabla de errores: `SKILL.md`. Detalle de la
API (bodies literales, estructura de `output`, FAQ de facturacion):
`references\api-web-search.md`.
