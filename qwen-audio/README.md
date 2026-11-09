# qwen-audio

Sintesis de voz (TTS) y transcripcion (ASR) con QwenCloud Token Plan (`sk-sp-` resuelta sola):

- **TTS** `qwen-audio-3.0-tts-plus`: WebSocket (default, verificado empiricamente) o HTTP
  one-shot `--http` (`POST /services/audio/tts/SpeechSynthesizer` → `output.audio.url`, 24 h).
  Voces verificadas: `longanlingxin` (F) / `longanlufeng` (M), espanol incluido.
- **ASR** `qwen-audio-3.0-asr-flash`: HTTP sincrono, audio <=5 min / <=10 MB, `--language-hints`
  (hasta 4 codigos).
- Documentales sin script: filetrans (pay-as-you-go solo) y realtime
  `wss://token-plan.maas.qwencloudapi.com/api-ws/v1/realtime?model=qwen-audio-3.0-realtime-plus`.

Ejemplo canonical:

```
py "%USERPROFILE%\.config\opencode\skills\qwen-audio\scripts\sintetizar_voz.py" --text "Hola, esto es una prueba." --output voz.mp3
py "%USERPROFILE%\.config\opencode\skills\qwen-audio\scripts\transcribir_audio.py" --audio voz.mp3 --language-hints es --output texto.txt
```

Guia completa: `SKILL.md`; protocolo WS literal, bodies HTTP, errores: `references/api-qwen-audio.md`.
