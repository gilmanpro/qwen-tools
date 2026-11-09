# qwen-web-extractor

Lectura del **contenido completo** de paginas web con QwenCloud via la tool
`web_extractor` de la **Responses API** (normalmente acompanada de `web_search` en el
mismo `tools[]`; sin stream requerido). Script Python solo-stdlib: acepta 1+ URLs, imprime
UN JSON con `extracted[]` (items `web_extractor_call`: goal/output) y `usage`. Gratis por
tiempo limitado (el bucket `extractor` del contador compartido es informativo: no consume
el limite de 30 busquedas web+imagen).

Ejemplo de invocacion (ruta canonical):

```
py "%USERPROFILE%\.config\opencode\skills\qwen-web-extractor\scripts\extraer_web.py" --url "https://example.com" --prompt "resume la pagina" --json
```

Las 3 vias (Responses / Chat+DashScope `agent_max` con stream / Anthropic `web_fetch`),
limitaciones (paginas publicas, truncado, JS dinamico, extraction fail silenciosa) y fees:
`SKILL.md`. Detalle de la API: `references\api-web-extractor.md`.
