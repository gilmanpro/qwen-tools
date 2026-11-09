# qwen-imagen

Genera y edita imagenes con QwenCloud (`qwen-image-3.0-pro`, `wan2.7-image`, `wan2.7-image-pro`):
posters, banners, infografias con texto renderizado, ilustracion realista 4K y edicion por
instruccion. Key del Token Plan (`sk-sp-`) resuelta sola; descarga automatica de los PNG (URLs
validas 24 h); elige modelo sin preguntar.

Ejemplo de invocacion canonical:

```
py "%USERPROFILE%\.config\opencode\skills\qwen-imagen\scripts\generar_imagen.py" --prompt-file prompt.txt --output poster.png --size 1696*960
```

Guia completa (auto-seleccion, costos, sizes, edicion, watermark, errores): `SKILL.md`; detalle
de API literal: `references/api-qwen-image.md`.

Skill para [OpenCode](https://opencode.ai) bajo el estandar [Agent Skills](https://agentskills.io).
