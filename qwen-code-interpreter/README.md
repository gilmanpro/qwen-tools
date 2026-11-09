# qwen-code-interpreter

Corre Python en el sandbox remoto de QwenCloud (Responses API, tool `code_interpreter`).
**Uso exclusivo del agente @5-dev, max 1-2 llamadas por tarea.** Temporalmente gratis
(solo tokens). Lee `SKILL.md` para la politica completa, la tabla de modelos y la cadena
de bases.

## Ejemplo (ruta canonical)

```
py "%USERPROFILE%\.config\opencode\skills\qwen-code-interpreter\scripts\ejecutar_codigo.py" --prompt "Usa el interprete de codigo para calcular factorial(20)" --json
```

Script solo-stdlib (`py` de Windows, sin `pip install`). Key `sk-sp-` resuelta sola
desde auth.json — nunca se imprime.
