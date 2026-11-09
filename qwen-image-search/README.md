# qwen-image-search

Busqueda de imagenes con QwenCloud: `web_search_image` (texto → fotos) e `image_search`
(imagen inversa → similares), via **Responses API** (unica via posible; unicas regiones
Singapur y Beijing-N2 — Token Plan = Singapur de fabrica). Script Python solo-stdlib con
pre-validacion gratuita de `--image` y contador diario compartido (30 busquedas
web+imagen/dia).

Ejemplo de invocacion (ruta canonical):

```
py "%USERPROFILE%\.config\opencode\skills\qwen-image-search\scripts\buscar_imagen.py" --query "gato siames" --json
```

Instrucciones completas, fees y tabla de errores: `SKILL.md`. Detalle de la API (bodies
literales, estructura de `output`, formatos de imagen, FAQ):
`references\api-image-search.md`.
