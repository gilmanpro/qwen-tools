# qwen-video

Genera video con QwenCloud via REST **asincrona** (submit + poll + descarga automatica del MP4 —
las URLs expiran en 24 h). Dos modelos en la allowlist del Token Plan (`sk-sp-` resuelta sola):

- **HappyHorse 1.1** `t2v` / `i2v` / `r2v`: 3-15 s, 480P/720P/1080P, audio automatico, 24 fps.
- **wan3.0-video** All-in-One: 2-30 s (o `-1` smart), 30 fps con audio nativo, ratio `adaptive`,
  referencias omni-modales (imagen/video/audio/documento/web), edicion y extension de video.
  **SI esta en Token Plan** (hallazgo R0 2026-11-09; `wan3.0-video-prime` NO).

Ejemplo canonical:

```
py "%USERPROFILE%\.config\opencode\skills\qwen-video\scripts\generar_video.py" --prompt-file prompt.txt --output video.mp4 --resolution 480P --duration 3
py "%USERPROFILE%\.config\opencode\skills\qwen-video\scripts\generar_video.py" --prompt "a cat running on the grass" --output clip.mp4 --model wan3.0-video --duration 5
```

Guia completa (parametros, costos por segundo, errores): `SKILL.md`; bodies API literales de
ambos modelos: `references/api-happyhorse-video.md`.
