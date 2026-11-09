# qwen-pdf

Lee y entiende PDFs con QwenCloud: resume o responde preguntas sobre un documento local
(o URL) via **Chat Completions / DashScope** — NUNCA Responses API (devuelve 200 sin
entregar el archivo). Limites: 150 MB / 256 paginas. Fee por pagina parseada con
`include_tool_usage:true`. Lee `SKILL.md` para la politica, la cadena de bases y la tabla
de errores; `references\api-pdf.md` para los bodies API literales.

## Ejemplo (ruta canonical)

```
py "%USERPROFILE%\.config\opencode\skills\qwen-pdf\scripts\leer_pdf.py" --file informe.pdf --pregunta "cuales son las conclusiones" --json
```

Script solo-stdlib con stream (`py` de Windows, sin `pip install`). Key resuelta sola —
nunca se imprime.
