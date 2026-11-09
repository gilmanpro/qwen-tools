# qwen-function-calling

Conecta los modelos QwenCloud a TUS funciones/APIs: el modelo pide tool calls, tu las
ejecutas y le devuelves el resultado (loop multi-turno). Cubre Chat Completions
(`tool_calls` anidados), Responses API (items `function_call`/`function_call_output`
**flat**) y las trampas por modelo (tool_choice "required" no soportado en Qwen,
`tool_stream:true` en GLM, agregacion de deltas en streaming, Omni, realtime WS
documental).

## Ejemplo (ruta canonical — demo del loop completo con clima simulado)

```
py "%USERPROFILE%\.config\opencode\skills\qwen-function-calling\scripts\plantilla_function_calling.py" --prompt "que tiempo hace en Tokyo" --json
```

La plantilla es una DEMOSTRACION ejecutable (solo-stdlib, key del Token Plan resuelta
sola) para adaptarla a tus herramientas. Documentacion completa: `SKILL.md`; bodies
literales: `references\api-function-calling.md`.
