# -*- coding: utf-8 -*-
"""Generador de videos QwenCloud (HappyHorse + wan3.0-video) — solo stdlib.

Flujo ASINCRONO (igual para ambos): submit (POST .../video-synthesis con header
X-DashScope-Async: enable) -> poll (GET /tasks/{id}) -> descarga MP4.

Uso:
  py generar_video.py --prompt-file prompt.txt --output video.mp4
  py generar_video.py --prompt-file prompt.txt --image foto.png --output video.mp4
  py generar_video.py --prompt-file prompt.txt --refs a.png,b.png --output video.mp4
  py generar_video.py --prompt-file prompt.txt --output video.mp4 --model wan3.0-video --duration 20

Modelos (se infieren si no se pasa --model):
  happyhorse-1.1-t2v  texto -> video            (default)
  happyhorse-1.1-i2v  imagen -> video           (con --image)
  happyhorse-1.1-r2v  referencias -> video      (con --refs, prompt cita [Image N])
  wan3.0-video        All-in-One (solo via --model explicito): texto/imagen/referencias,
                      2-30 s o -1 (duracion smart), ratio "adaptive"; esta EN la allowlist
                      del Token Plan (hallazgo R0, verificado 2026-11-09 en
                      docs.qwencloud.com/token-plan/.../supported-models).
                      wan3.0-video-prime NO esta en Token Plan (fuera de allowlist).

API key (en orden de busqueda):
  1. env DASHSCOPE_API_KEY
  2. env ANTHROPIC_AUTH_TOKEN (convencion Token Plan)
  3. ~/.local/share/opencode/auth.json (providers alibaba-token-plan / -cn)
Base URL: keys sk-sp-* (Token Plan) -> https://token-plan.maas.qwencloudapi.com/api/v1
          (las bases Token Plan NO llevan region ID; Token Plan solo en Singapur)
          resto (pay-as-you-go)     -> https://ap-southeast-1.maas.qwencloudapi.com/api/v1
          (forma con region ID segun doc regions; "maas.qwencloudapi.com" pelada es su
          alias equivalente de Singapur)
Exit codes: 0 OK | 1 error de API/generacion/descarga | 2 configuracion/uso.
Skill hija del split multimedia (2026-11-09).
"""
import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

BASE_PAYG = "https://ap-southeast-1.maas.qwencloudapi.com/api/v1"
BASE_TOKEN_PLAN = "https://token-plan.maas.qwencloudapi.com/api/v1"
ENDPOINT_SUBMIT = "/services/aigc/video-generation/video-synthesis"

MODELS = {"t2v": "happyhorse-1.1-t2v", "i2v": "happyhorse-1.1-i2v", "r2v": "happyhorse-1.1-r2v"}
WAN_MODEL = "wan3.0-video"  # All-in-One; EN la allowlist del Token Plan (hallazgo R0)
MODELOS_TOKEN_PLAN = tuple(MODELS.values()) + (WAN_MODEL,)  # wan3.0-video-prime NO esta en TP
RESOLUTIONS = ("480P", "720P", "1080P")
RATIOS_HAPPYHORSE = ("16:9", "9:16", "1:1", "4:3", "3:4", "4:5", "5:4", "9:21", "21:9")
RATIOS_WAN = ("adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16")  # adaptive SOLO wan3.0
RATIOS = tuple(sorted(set(RATIOS_HAPPYHORSE) | set(RATIOS_WAN)))  # choices de --ratio (validacion por modelo abajo)
MIME_IMG = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
MAX_IMG_BYTES = 20 * 1024 * 1024
HTTP_TIMEOUT = 120


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


def hint_error(code, msg, http_code=None):
    """Pista segun codigo de error (submit o poll FAILED)."""
    c = str(code or "")
    m = str(msg or "").lower()
    if c == "InvalidApiKey" or http_code == 401:
        return "key invalida o base URL incorrecta (sk-sp-* => token-plan.maas.qwencloudapi.com)"
    if c == "DataInspectionFailed":
        return "prompt/imagen bloqueado por moderacion: reescribir el prompt o cambiar la imagen"
    if c == "InvalidParameter":
        return ("parametro fuera de rango: duration 3-15 (happyhorse) / 2-30 o -1 (wan3.0), "
                "resolution 480P/720P/1080P, ratio valido para el modelo, refs 1-9 (happyhorse) / 1-10 (wan3.0)")
    if c == "Arrearage":
        return "cuenta con saldo pendiente (arrearage): regulariza el pago en la consola"
    if c == "IPInfringementSuspect":
        return "posible infraccion de propiedad intelectual en prompt/imagen: reformular"
    if "not exist" in m or "model" in c.lower():
        return ("modelo no disponible en tu plan; Token Plan allowlist: " + " / ".join(MODELOS_TOKEN_PLAN)
                + " (wan3.0-video-prime NO esta en Token Plan)")
    if http_code == 403:
        return "acceso denegado: verifica que el modelo este habilitado en tu cuenta"
    if c.startswith("Throttling") or http_code == 429:
        return "rate limit: esperar y reintentar"
    return None


def parse_http_error(e):
    raw = e.read().decode("utf-8", "replace")
    try:
        err = json.loads(raw)
        return err.get("code") or "", err.get("message") or raw[:300]
    except ValueError:
        return "", raw[:300]


def a_media_uri(ref, etiqueta):
    """Devuelve la URL tal cual si ya es URL/data URI; si es ruta local, data URI base64."""
    if re.match(r"^(https?://|data:)", ref, re.I):
        return ref
    if not os.path.isfile(ref):
        fallo(f"{etiqueta}: no existe el archivo '{ref}'", "usa una URL publica o una ruta local valida", 2)
    tam = os.path.getsize(ref)
    if tam > MAX_IMG_BYTES:
        fallo(f"{etiqueta}: '{ref}' pesa {tam // (1024 * 1024)} MB (maximo 20 MB)",
              "comprime o redimensiona la imagen (JPEG/PNG/WEBP)", 2)
    ext = os.path.splitext(ref)[1].lower()
    mime = MIME_IMG.get(ext)
    if not mime:
        fallo(f"{etiqueta}: extension no soportada '{ext}' en '{ref}'", "solo JPEG/PNG/WEBP", 2)
    with open(ref, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def main():
    ap = argparse.ArgumentParser(description="Generacion de video con HappyHorse / wan3.0-video (QwenCloud, API asincrona submit+poll)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--prompt", help="prompt directo (cuidado con quoting en cmd)")
    g.add_argument("--prompt-file", help="archivo .txt con el prompt (recomendado en Windows)")
    ap.add_argument("--output", required=True, help="ruta del MP4 de salida (obligatorio)")
    ap.add_argument("--model", default=None,
                    help="default: inferir (con --image i2v; con --refs r2v; si no t2v). "
                         "Alternativa: --model wan3.0-video (All-in-One, 2-30 s o -1, ratio adaptive)")
    ap.add_argument("--image", default=None, help="i2v: URL o ruta local de la imagen de primer frame (exactamente 1)")
    ap.add_argument("--refs", default=None, help="r2v: 1-9 imagenes de referencia (wan3.0: hasta 10), URL|ruta local separadas por comas")
    ap.add_argument("--resolution", choices=RESOLUTIONS, default="720P",
                    help="default del script 720P por costo (la API usa 1080P)")
    ap.add_argument("--ratio", choices=RATIOS, default=None,
                    help="happyhorse: 16:9 default (omitir en i2v); wan3.0-video: default adaptive "
                         "(adaptive NO existe en happyhorse; 4:5/5:4/9:21 NO existen en wan3.0)")
    ap.add_argument("--duration", type=int, default=5,
                    help="segundos de video: happyhorse 3-15 (default 5); wan3.0-video 2-30 o -1 (duracion smart)")
    ap.add_argument("--watermark", action="store_true",
                    help="anadir marca de agua (OFF por defecto: el script envia watermark:false explicito)")
    ap.add_argument("--seed", type=int, default=None, help="0-2147483647 (opcional)")
    ap.add_argument("--base-url", default=None, help="forzar base URL (default: auto segun prefijo de key)")
    ap.add_argument("--timeout", type=int, default=900, help="timeout total de espera de la tarea, segundos")
    ap.add_argument("--poll-interval", type=float, default=15, help="cadencia inicial del poll (x1.5 hasta 60 s)")
    args = ap.parse_args()

    key = resolver_key()
    if not key:
        fallo("sin API key (DASHSCOPE_API_KEY / ANTHROPIC_AUTH_TOKEN / opencode auth.json)",
              "crearla en https://home.qwencloud.com/api-keys y exportarla (Windows: setx DASHSCOPE_API_KEY sk-xxx)", 2)
    base = args.base_url or (BASE_TOKEN_PLAN if key.startswith("sk-sp-") else BASE_PAYG)
    api_submit = base.rstrip("/") + ENDPOINT_SUBMIT

    prompt = args.prompt
    if args.prompt_file:
        try:
            with open(args.prompt_file, encoding="utf-8") as f:
                prompt = f.read().strip()
        except OSError as e:
            fallo(f"no puedo leer --prompt-file: {e}", None, 2)

    # --- modo / modelo ---
    if args.image and args.refs:
        fallo("no combinar --image (i2v) y --refs (r2v): elige un solo modo", None, 2)
    kind = "i2v" if args.image else ("r2v" if args.refs else "t2v")
    model = args.model or MODELS[kind]
    for suf, nombre in MODELS.items():
        if suf in model and suf != kind and args.model:
            fallo(f"--model {model} no coincide con los insumos dados (detectado: {MODELS[kind]})",
                  "i2v requiere --image; r2v requiere --refs; t2v solo prompt", 2)

    # --- validaciones (por modelo) ---
    if model == WAN_MODEL:
        if not (args.duration == -1 or 2 <= args.duration <= 30):
            fallo("--duration fuera de rango para wan3.0-video (2-30 segundos, o -1 = duracion smart)", None, 2)
        if args.ratio is not None and args.ratio not in RATIOS_WAN:
            fallo(f"--ratio '{args.ratio}' no existe en wan3.0-video (validos: {', '.join(RATIOS_WAN)})", None, 2)
    else:
        if not 3 <= args.duration <= 15:
            fallo("--duration fuera de rango para happyhorse (3-15 segundos)", None, 2)
        if args.ratio is not None and args.ratio not in RATIOS_HAPPYHORSE:
            fallo(f"--ratio '{args.ratio}' no existe en happyhorse (validos: {', '.join(RATIOS_HAPPYHORSE)}; "
                  "'adaptive' es SOLO de wan3.0-video)", None, 2)
    if args.seed is not None and not 0 <= args.seed <= 2147483647:
        fallo("--seed fuera de rango (0-2147483647)", None, 2)
    refs = [r.strip() for r in args.refs.split(",") if r.strip()] if args.refs else []
    max_refs = 10 if model == WAN_MODEL else 9
    if kind == "r2v" and not 1 <= len(refs) <= max_refs:
        fallo(f"--refs requiere entre 1 y {max_refs} imagenes separadas por comas ({model})", None, 2)
    if kind in ("t2v", "r2v") and not prompt:
        fallo(f"el modelo {model} requiere --prompt o --prompt-file", None, 2)

    # --- body ---
    input_ = {}
    if kind == "t2v":
        input_["prompt"] = prompt
    elif kind == "i2v":
        if prompt:
            input_["prompt"] = prompt
        input_["media"] = [{"type": "first_frame", "url": a_media_uri(args.image, "--image")}]
    else:  # r2v
        input_["prompt"] = prompt
        input_["media"] = [{"type": "reference_image", "url": a_media_uri(r, f"--refs[{i + 1}]")}
                           for i, r in enumerate(refs)]

    if model == WAN_MODEL:
        # wan3.0-video: NO documenta `watermark` ni `seed` en la doc publica (verificar
        # empiricamente en F2) -> `watermark` SOLO se envia si el usuario la pide explicita.
        params = {"resolution": args.resolution, "duration": args.duration}
        if args.watermark:
            params["watermark"] = True
        params["ratio"] = args.ratio or "adaptive"  # adaptive = default de la API wan3.0
        # NO enviar negative_prompt (no documentado en wan3.0); prompt_extend si existe en
        # wan3.0 (doc lo usa en sus ejemplos) pero el script no lo expone: default del servidor.
    else:
        # HappyHorse: la API default watermark=TRUE -> enviar SIEMPRE false explicito salvo --watermark
        params = {"resolution": args.resolution, "duration": args.duration, "watermark": bool(args.watermark)}
        if kind != "i2v":
            params["ratio"] = args.ratio or "16:9"
    if args.seed is not None:
        params["seed"] = args.seed
    # NO enviar prompt_extend ni negative_prompt en happyhorse: no los soporta (HTTP 400 InvalidParameter)

    body = json.dumps({"model": model, "input": input_, "parameters": params}, ensure_ascii=False).encode("utf-8")

    # --- submit (con reintentos en 429/Throttling) ---
    t0 = time.time()
    req = urllib.request.Request(api_submit, data=body, headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer " + key,
        "X-DashScope-Async": "enable",
    })
    intentos = 0
    while True:
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
                resp = json.loads(r.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as e:
            code, msg = parse_http_error(e)
            if (e.code == 429 or str(code).startswith("Throttling")) and intentos < 2:
                intentos += 1
                esperar = 10 * intentos
                print(f"[submit] rate limit (HTTP {e.code} {code}); reintento {intentos}/2 en {esperar} s",
                      file=sys.stderr)
                time.sleep(esperar)
                continue
            fallo(f"submit HTTP {e.code} {code} {msg}", hint_error(code, msg, e.code), 1)
        except Exception as e:
            fallo(f"conexion submit: {e}", "revisar red/proxy", 1)

    out = resp.get("output", {}) if isinstance(resp.get("output"), dict) else {}
    task_id = out.get("task_id")
    request_id = resp.get("request_id")
    if not task_id:
        fallo("el submit no devolvio task_id: " + json.dumps(resp, ensure_ascii=False)[:400], None, 1)
    print(f"[submit] task_id={task_id} status={out.get('task_status', '?')} — "
          f"controles de calidad/seguridad pueden rechazar aun la tarea", file=sys.stderr)

    # --- poll ---
    api_task = base.rstrip("/") + "/tasks/" + task_id
    interval = max(float(args.poll_interval), 1.0)
    deadline = t0 + args.timeout
    status = "PENDING"
    data = None
    while True:
        try:
            req = urllib.request.Request(api_task, headers={"Authorization": "Bearer " + key})
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
                data = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            code, msg = parse_http_error(e)
            if e.code == 429 or str(code).startswith("Throttling") or e.code >= 500:
                print(f"[poll] transitorio HTTP {e.code} {code}; reintentando", file=sys.stderr)
                data = None
            else:
                fallo(f"poll HTTP {e.code} {code} {msg}", hint_error(code, msg, e.code), 1)
        except Exception as e:
            print(f"[poll] error de red transitorio: {e}; reintentando", file=sys.stderr)
            data = None

        if data is not None:
            out = data.get("output", {}) if isinstance(data.get("output"), dict) else {}
            status = out.get("task_status") or "UNKNOWN"
            if status == "SUCCEEDED":
                break
            if status == "FAILED":
                code = out.get("code") or ""
                msg = out.get("message") or ""
                fallo(f"tarea FAILED: {code} {msg}", hint_error(code, msg), 1)
            if status == "CANCELED":
                fallo("tarea CANCELED", None, 1)
            if status == "UNKNOWN":
                fallo("tarea expirada (status UNKNOWN: la informacion de la tarea solo se conserva 24 h)",
                      "reintentar la generacion desde el principio", 1)
        print(f"[poll] {status} ({int(time.time() - t0)} s) — proximo chequeo en {int(interval)} s",
              file=sys.stderr)

        if time.time() + interval > deadline:
            fallo(f"timeout: la tarea {task_id} no termino en {args.timeout} s (ultimo estado: {status})",
                  "sube --timeout o reduce resolution/duration", 1)
        time.sleep(interval)
        interval = min(interval * 1.5, 60.0)

    # --- exito: descargar el MP4 ya (la URL expira en 24 h) ---
    out = data.get("output", {})
    video_url = out.get("video_url")
    if not video_url:
        fallo("SUCCEEDED sin video_url: " + json.dumps(data, ensure_ascii=False)[:400], None, 1)

    d = os.path.dirname(os.path.abspath(args.output))
    if d:
        os.makedirs(d, exist_ok=True)
    errores = 0
    while True:
        try:
            with urllib.request.urlopen(video_url, timeout=HTTP_TIMEOUT) as r, open(args.output, "wb") as f:
                f.write(r.read())
            break
        except Exception as e:
            errores += 1
            if errores >= 3:
                fallo(f"descargando video: {e}",
                      "la URL expira en 24 h; si persiste, reintentar la generacion", 1)
            print(f"[download] reintento {errores}/3 tras error: {e}", file=sys.stderr)
            time.sleep(5)

    print(json.dumps({
        "ok": True,
        "request_id": request_id,
        "task_id": task_id,
        "model": model,
        "base": base,
        "video": os.path.abspath(args.output),
        "segundos": round(time.time() - t0, 1),
        "usage": data.get("usage", {}),
    }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
