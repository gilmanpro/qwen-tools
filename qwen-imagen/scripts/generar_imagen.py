# -*- coding: utf-8 -*-
"""Generador de imagenes QwenCloud (Qwen-Image) — solo stdlib.

Uso:
  py generar_imagen.py --prompt "..." --output imagen.png
  py generar_imagen.py --prompt-file prompt.txt --output imagen.png --size 2048*2048 --n 2

API key (en orden de busqueda):
  1. env DASHSCOPE_API_KEY
  2. env ANTHROPIC_AUTH_TOKEN (convencion Token Plan)
  3. ~/.local/share/opencode/auth.json (providers alibaba-token-plan / -cn)
Base URL: keys sk-sp-* (Token Plan) -> https://token-plan.maas.qwencloudapi.com/api/v1
          (las bases Token Plan NO llevan region ID; Token Plan solo en Singapur)
          resto (pay-as-you-go)     -> https://ap-southeast-1.maas.qwencloudapi.com/api/v1
          (forma con region ID segun doc regions; "maas.qwencloudapi.com" pelada es su
          alias equivalente de Singapur)
Exit codes: 0 OK | 1 error de API/descarga | 2 configuracion/uso.
Skill hija del split multimedia (2026-11-09).
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

BASE_PAYG = "https://ap-southeast-1.maas.qwencloudapi.com/api/v1"
BASE_TOKEN_PLAN = "https://token-plan.maas.qwencloudapi.com/api/v1"
ENDPOINT = "/services/aigc/multimodal-generation/generation"


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


def main():
    ap = argparse.ArgumentParser(description="Text-to-image con Qwen-Image (QwenCloud)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--prompt", help="prompt directo (cuidado con quoting en cmd)")
    g.add_argument("--prompt-file", help="archivo .txt con el prompt (recomendado en Windows)")
    ap.add_argument("--output", required=True, help="ruta del PNG de salida")
    ap.add_argument("--model", default="qwen-image-3.0-pro")
    ap.add_argument("--size", default=None, help='"ancho*alto" p.ej. 2048*2048 (omitir = auto)')
    ap.add_argument("--n", type=int, default=1, help="1-6 imagenes (costo x n; probar con 1)")
    ap.add_argument("--negative", default="", help="negative_prompt (<=500 chars)")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--no-extend", action="store_true", help="desactiva prompt_extend")
    ap.add_argument("--extend-mode", choices=["direct", "agent"], default=None, help="solo serie 3.0, solo T2I")
    ap.add_argument("--no-thinking", action="store_true", help="desactiva enable_thinking (solo 3.0)")
    ap.add_argument("--watermark", action="store_true")
    ap.add_argument("--base-url", default=None, help="forzar base URL (default: auto segun prefijo de key)")
    ap.add_argument("--timeout", type=int, default=300)
    args = ap.parse_args()

    key = resolver_key()
    if not key:
        fallo("sin API key (DASHSCOPE_API_KEY / ANTHROPIC_AUTH_TOKEN / opencode auth.json)",
              "crearla en https://home.qwencloud.com/api-keys y exportarla (Windows: setx DASHSCOPE_API_KEY sk-xxx)", 2)
    base = args.base_url or (BASE_TOKEN_PLAN if key.startswith("sk-sp-") else BASE_PAYG)
    api = base.rstrip("/") + ENDPOINT

    prompt = args.prompt
    if args.prompt_file:
        try:
            with open(args.prompt_file, encoding="utf-8") as f:
                prompt = f.read().strip()
        except OSError as e:
            fallo(f"no puedo leer --prompt-file: {e}", None, 2)
    if not prompt:
        fallo("falta --prompt o --prompt-file", None, 2)
    if not 1 <= args.n <= 6:
        fallo("--n fuera de rango (1-6)", None, 2)
    if args.size and not re.match(r"^\d+\*\d+$", args.size):
        fallo('--size debe ser "ancho*alto" (p.ej. 2048*2048)', None, 2)

    params = {"prompt_extend": not args.no_extend, "watermark": args.watermark, "n": args.n}
    if args.negative:
        params["negative_prompt"] = args.negative[:500]
    if args.size:
        params["size"] = args.size
    if args.seed is not None:
        params["seed"] = args.seed
    if args.extend_mode:
        params["prompt_extend_mode"] = args.extend_mode
    if args.no_thinking:
        params["enable_thinking"] = False

    body = json.dumps({
        "model": args.model,
        "input": {"messages": [{"role": "user", "content": [{"text": prompt}]}]},
        "parameters": params,
    }).encode("utf-8")

    req = urllib.request.Request(api, data=body, headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer " + key,
    })

    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=args.timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            err = json.loads(raw)
            code, msg = err.get("code") or "", err.get("message") or raw[:300]
        except ValueError:
            code, msg = "", raw[:300]
        hint = None
        if e.code == 429 or str(code).startswith("Throttling"):
            hint = "rate limit: esperar 5-15 s y reintentar"
        elif code == "DataInspectionFailed":
            hint = "prompt bloqueado por moderacion: reescribirlo"
        elif e.code == 401:
            hint = "key invalida o base URL incorrecta (sk-sp-* => token-plan.maas.qwencloudapi.com)"
        elif e.code == 400 and ("model" in msg.lower() or "Model" in str(code)):
            hint = "modelo no disponible en tu plan; Token Plan: qwen-image-3.0-pro, wan2.7-image, wan2.7-image-pro"
        fallo(f"HTTP {e.code} {code} {msg}", hint, 1)
    except Exception as e:
        fallo(f"conexion: {e}", "revisar red/proxy", 1)

    urls = []
    for ch in data.get("output", {}).get("choices", []):
        for c in ch.get("message", {}).get("content", []):
            if isinstance(c, dict) and c.get("image"):
                urls.append(c["image"])
    if not urls:
        fallo("la respuesta no trajo imagenes: " + json.dumps(data)[:400], None, 1)

    out_base, ext = os.path.splitext(args.output)
    ext = ext.lower() or ".png"
    guardadas = []
    for i, u in enumerate(urls):
        path = args.output if len(urls) == 1 else f"{out_base}_{i + 1}{ext}"
        d = os.path.dirname(os.path.abspath(path))
        if d:
            os.makedirs(d, exist_ok=True)
        try:
            with urllib.request.urlopen(u, timeout=args.timeout) as r, open(path, "wb") as f:
                f.write(r.read())
        except Exception as e:
            fallo(f"descargando imagen {i + 1}: {e}", "las URLs expiran en 24 h; reintentar generacion", 1)
        guardadas.append(path)

    uso = data.get("usage", {})
    dims = f'{uso.get("output_width", "?")}x{uso.get("output_height", "?")}'
    print(json.dumps({
        "ok": True,
        "request_id": data.get("request_id"),
        "model": args.model,
        "base": base,
        "dimensiones": dims,
        "imagenes": guardadas,
        "segundos": round(time.time() - t0, 1),
    }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
