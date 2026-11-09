# -*- coding: utf-8 -*-
"""Transcriptor de audio QwenCloud (ASR sincrono) — solo stdlib.

Uso:
  py transcribir_audio.py --audio voz.mp3
  py transcribir_audio.py --audio https://ejemplo.com/podcast.wav --output out.txt
  py transcribir_audio.py --audio clip.mp3 --context "nombres de la empresa" --json

Modelo: qwen-audio-3.0-asr-flash (HTTP sincrono, mismo endpoint que imagenes).
El texto de la respuesta viene en output.text (NO en choices; ver references).

API key (en orden de busqueda):
  1. env DASHSCOPE_API_KEY
  2. env ANTHROPIC_AUTH_TOKEN (convencion Token Plan)
  3. ~/.local/share/opencode/auth.json (providers alibaba-token-plan / -cn)
Base URL: keys sk-sp-* (Token Plan) -> https://token-plan.maas.qwencloudapi.com/api/v1
          (las bases Token Plan NO llevan region ID; Token Plan solo en Singapur)
          resto (pay-as-you-go)     -> https://ap-southeast-1.maas.qwencloudapi.com/api/v1
          (forma con region ID segun doc regions; "maas.qwencloudapi.com" pelada es su
          alias equivalente de Singapur)
Limites del audio: <=5 min de duracion, <=10 MB (local: base64 solo si <=7 MB).
Idiomas: autodeteccion por defecto; --language-hints (doc TP: parameters.language_hints,
hasta 4 codigos, p.ej. "es,en") mejora la precision cuando el idioma se conoce.
Exit codes: 0 OK | 1 error de API/audio | 2 configuracion/uso.
Skill hija del split multimedia (2026-11-09).
"""
import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE_PAYG = "https://ap-southeast-1.maas.qwencloudapi.com/api/v1"
BASE_TOKEN_PLAN = "https://token-plan.maas.qwencloudapi.com/api/v1"
ENDPOINT = "/services/aigc/multimodal-generation/generation"
MODELO_DEFAULT = "qwen-audio-3.0-asr-flash"

# Extensiones aceptadas por la API (17 formatos) -> mime para el data URI
MIME_BY_EXT = {
    "aac": "audio/aac", "amr": "audio/amr", "avi": "video/x-msvideo",
    "flac": "audio/flac", "flv": "video/x-flv", "m4a": "audio/mp4",
    "mkv": "video/x-matroska", "mov": "video/quicktime", "mp3": "audio/mpeg",
    "mp4": "video/mp4", "mpeg": "audio/mpeg", "ogg": "audio/ogg",
    "opus": "audio/opus", "wav": "audio/wav", "webm": "audio/webm",
    "wma": "audio/x-ms-wma", "wmv": "video/x-ms-wmv",
}
LIMITE_BASE64 = 7 * 1024 * 1024   # >7 MB local ya no se manda en base64 (limite API: 10 MB)
REINTENTOS_429 = 2                 # maximo 2 reintentos con espera 5-15 s


def resolver_key():
    key = os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    if key:
        return key.strip()
    auth_path = os.path.join(os.path.expanduser("~"), ".local", "share", "opencode", "auth.json")
    try:
        with open(auth_path, encoding="utf-8") as f:
            auth = json.load(f)
        for prov in ("alibaba-token-plan", "alibaba-token-plan-cn"):
            k = (auth.get(prov) or {}).get("key")
            if k:
                return k.strip()
    except (OSError, ValueError):
        pass
    return None


def fallo(msg, hint=None, code=1):
    print("ERROR: " + msg)
    if hint:
        print("SUGERENCIA: " + hint)
    sys.exit(code)


def hint_de_error(code, msg, http_code):
    """Sugerencias segun el catalogo de errores de QwenCloud."""
    c = str(code or "")
    m = str(msg or "")
    if http_code == 429 or c.startswith("Throttling"):
        return "rate limit: esperar 5-15 s y reintentar (max 2)"
    if http_code == 401 or c == "InvalidApiKey":
        return "key invalida o base URL incorrecta (sk-sp-* => token-plan.maas.qwencloudapi.com)"
    if c == "DataInspectionFailed":
        return "audio bloqueado por moderacion de contenido"
    if c == "InvalidFile.AudioLengthError" or "audio length" in m.lower():
        return "duracion fuera de limite: el audio debe durar entre 1 y 300 segundos (<=5 min)"
    if "audio is empty" in m.lower():
        return "audio demasiado corto o sin voz reconocible (>1 s de audio valido)"
    if c == "InvalidFile.DownloadFailed" or "download" in m.lower():
        return "la URL del audio no es descargable: verificar acceso publico directo (sin login/redirecciones)"
    if "max bytes per data-uri" in m.lower() or "10485760" in m:
        return "el data URI supera 10 MB: subir el audio a una URL publica y pasarla a --audio"
    if http_code == 400 and "model" in m.lower():
        return "modelo no disponible en tu plan; Token Plan: qwen-audio-3.0-asr-flash"
    return None


def es_url(texto):
    try:
        p = urllib.parse.urlparse(texto)
        return p.scheme in ("http", "https")
    except ValueError:
        return False


def inferir_ext_desde_url(url):
    path = urllib.parse.urlparse(url).path
    return os.path.splitext(path)[1].lower().lstrip(".")


def preparar_audio(ruta_o_url):
    """Devuelve (data_field, extension). Local <=7 MB -> data URI base64."""
    if es_url(ruta_o_url) or ruta_o_url.startswith("data:"):
        ext = inferir_ext_desde_url(ruta_o_url)
        if not ext or ext not in MIME_BY_EXT:
            fallo(f"no puedo determinar el formato desde la URL (ext='{ext or 'ninguna'}); "
                  "usa una URL que termine en .mp3/.wav/.m4a/... o sube el archivo local",
                  f"extensiones validas: {', '.join(sorted(MIME_BY_EXT))}", 2)
        return ruta_o_url, ext

    # archivo local
    if not os.path.isfile(ruta_o_url):
        fallo(f"audio no encontrado: {ruta_o_url}", "verifica la ruta (o pasa una URL publica)", 2)
    ext = os.path.splitext(ruta_o_url)[1].lower().lstrip(".")
    if ext not in MIME_BY_EXT:
        fallo(f"extension no soportada: .{ext or '(sin extension)'}",
              f"formatos aceptados: {', '.join(sorted(MIME_BY_EXT))} (<=5 min, <=10 MB)", 2)
    tam = os.path.getsize(ruta_o_url)
    if tam > LIMITE_BASE64:
        fallo("audio demasiado grande para base64 (limite 10MB): sube a una URL publica",
              f"archivo local de {tam / 1048576:.1f} MB; la API rechaza data-uri >10485760 bytes", 1)
    try:
        with open(ruta_o_url, "rb") as f:
            raw = f.read()
    except OSError as e:
        fallo(f"leyendo el audio: {e}", None, 2)
    data_uri = f"data:{MIME_BY_EXT[ext]};base64," + base64.b64encode(raw).decode("ascii")
    return data_uri, ext


def extraer_texto(output):
    """PARSEO ESPECIFICO de ASR: output.text es la via principal (NO choices)."""
    if not isinstance(output, dict):
        return None
    t = output.get("text")
    if isinstance(t, str) and t.strip():
        return t
    inner = output.get("output")
    if isinstance(inner, dict):
        s = inner.get("sentence")
        if isinstance(s, dict) and isinstance(s.get("text"), str) and s["text"].strip():
            return s["text"]
    partes = []
    for ch in output.get("choices") or []:
        if not isinstance(ch, dict):
            continue
        msg = ch.get("message") or {}
        for c in msg.get("content") or []:
            if isinstance(c, dict) and isinstance(c.get("text"), str):
                partes.append(c["text"])
    joined = "".join(partes).strip()
    return joined or None


def llamar_api(api, key, body_bytes, timeout):
    req = urllib.request.Request(api, data=body_bytes, headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer " + key,
        "X-DashScope-SSE": "disable",
    })
    ultimo = None
    for intento in range(REINTENTOS_429 + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            try:
                err = json.loads(raw)
                code = err.get("code") or ""
                msg = err.get("message") or raw[:300]
            except ValueError:
                code, msg = "", raw[:300]
            if (e.code == 429 or str(code).startswith("Throttling")) and intento < REINTENTOS_429:
                espera = 5 + 5 * intento
                print(f"AVISO: 429/Throttling, reintentando en {espera} s "
                      f"({intento + 1}/{REINTENTOS_429})...", file=sys.stderr)
                time.sleep(espera)
                ultimo = (e.code, code, msg)
                continue
            fallo(f"HTTP {e.code} {code} {msg}", hint_de_error(code, msg, e.code), 1)
        except Exception as e:
            fallo(f"conexion: {e}", "revisar red/proxy", 1)
    if ultimo:
        fallo(f"HTTP {ultimo[0]} {ultimo[1]} {ultimo[2]} (tras {REINTENTOS_429} reintentos)",
              "rate limit persistente: esperar mas tiempo o reducir frecuencia", 1)


def main():
    ap = argparse.ArgumentParser(description="ASR sincrono con qwen-audio-3.0-asr-flash (QwenCloud)")
    ap.add_argument("--audio", required=True, help="ruta local (<=7 MB -> base64) o URL publica del audio")
    ap.add_argument("--output", default=None, help="guardar la transcripcion en un archivo .txt")
    ap.add_argument("--json", action="store_true", help="incluir el volcado completo de la respuesta")
    ap.add_argument("--context", default=None,
                    help="texto de contexto para mejorar nombres/terminos (experimental)")
    ap.add_argument("--sample-rate", default=None,
                    help="frecuencia de muestreo (string) si la API no la detecta; opcional")
    ap.add_argument("--language-hints", default=None,
                    help='codigos de idioma, hasta 4 separados por comas (p.ej. "es,en"); '
                         "autodeteccion si se omite (parameters.language_hints, doc TP)")
    ap.add_argument("--model", default=MODELO_DEFAULT)
    ap.add_argument("--base-url", default=None, help="forzar base URL (default: auto segun prefijo de key)")
    ap.add_argument("--timeout", type=int, default=300)
    args = ap.parse_args()

    key = resolver_key()
    if not key:
        fallo("sin API key (DASHSCOPE_API_KEY / ANTHROPIC_AUTH_TOKEN / opencode auth.json)",
              "crearla en https://home.qwencloud.com/api-keys y exportarla (Windows: setx DASHSCOPE_API_KEY sk-xxx)", 2)
    base = args.base_url or (BASE_TOKEN_PLAN if key.startswith("sk-sp-") else BASE_PAYG)
    api = base.rstrip("/") + ENDPOINT

    data_field, ext = preparar_audio(args.audio)

    content = []
    if args.context:
        content.append({"type": "input_text", "text": args.context})
    content.append({"type": "input_audio", "input_audio": {"data": data_field}})

    params = {"format": ext}
    if args.sample_rate:
        params["sample_rate"] = str(args.sample_rate)
    if args.language_hints:
        # parameters.language_hints: array[string] (hasta 4; si hay mas, la API usa los 4 primeros
        # — el script corta aqui para que el JSON enviado sea exacto y no dependa del servidor)
        hints = [h.strip().lower() for h in args.language_hints.split(",") if h.strip()]
        if not hints:
            fallo("--language-hints vacio tras parsear (usa p.ej. 'es,en')", None, 2)
        if len(hints) > 4:
            print(f"AVISO: language_hints admite maximo 4; uso los primeros: {','.join(hints[:4])}",
                  file=sys.stderr)
        params["language_hints"] = hints[:4]

    body = json.dumps({
        "model": args.model,
        "input": {"messages": [{"role": "user", "content": content}]},
        "parameters": params,
    }).encode("utf-8")

    t0 = time.time()
    data = llamar_api(api, key, body, args.timeout)

    output = data.get("output") or {}
    texto = extraer_texto(output)
    if texto is None:
        fallo("la respuesta no trajo texto reconocido: " + json.dumps(data, ensure_ascii=False)[:500],
              "si el audio esta en un idioma no soportado o solo contiene ruido, retry no ayuda", 1)

    if args.output:
        d = os.path.dirname(os.path.abspath(args.output))
        if d:
            os.makedirs(d, exist_ok=True)
        try:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(texto)
        except OSError as e:
            fallo(f"escribiendo --output: {e}", None, 1)
        print(f"[guardado: {os.path.abspath(args.output)}]", file=sys.stderr)

    resumen = {
        "ok": True,
        "request_id": data.get("request_id"),
        "model": args.model,
        "texto": texto,
        "caracteres": len(texto),
        "segundos": round(time.time() - t0, 1),
    }
    if args.json:
        resumen["respuesta_completa"] = data
    print(json.dumps(resumen, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
