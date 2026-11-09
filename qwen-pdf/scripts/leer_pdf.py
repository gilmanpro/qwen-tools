# -*- coding: utf-8 -*-
r"""Lee y entiende PDFs con QwenCloud (via Chat Completions o DashScope) — solo stdlib.

El modelo parsea el PDF (texto + imagenes) y responde a tu pregunta sobre el documento.
NO usar la Responses API para esto: devuelve HTTP 200 SIN entregar el archivo al modelo
(trampa documentada en SKILL.md). Este script usa SIEMPRE /chat/completions con stream.

Uso:
  py leer_pdf.py --file informe.pdf --pregunta "cuales son las conclusiones"
  py leer_pdf.py --file-url "https://.../1506.02640v5.pdf" --json
  py leer_pdf.py --file grande.pdf --out .tmp\respuesta_pdf.json --timeout 300

El script:
  1. --file (ruta local): valida extension PDF (magic %PDF), tamano <=150 MB y lo
     codifica a data URI `data:application/pdf;base64,...` con `filename` OBLIGATORIO.
     El base64 infla ~1/3 el cuerpo: para archivos grandes usa --file-url.
  2. POST {base}/chat/completions con content=[{type:"file",file:{...}},{type:"text",
     text:"<pregunta>"}], stream:true, stream_options {include_usage:true} y
     include_tool_usage:true TOP-LEVEL (raw HTTP; en el SDK de OpenAI iria extra_body).
  3. Acumula los deltas de contenido del stream SSE (el parsing del PDF puede tardar:
     first-token hasta 300 s -> el --timeout default es 300).
  4. Paginas parseadas facturadas: usage.x_tools.pdf_page_parser.count (requiere
     include_tool_usage:true).
  5. Salida por defecto HUMANA (texto respondido en vivo); con --json UN unico JSON en
     stdout. Diagnosticos siempre por stderr.
  6. NUNCA imprime la API key (ni en errores); --out guarda el resultado JSON saneado.

Resolucion de key y base (Familia B — DashScope/compatible-mode, precedencia):
  1) DASHSCOPE_API_KEY  2) ANTHROPIC_AUTH_TOKEN  3) auth.json (alibaba-token-plan / -cn).
Host segun prefijo de la key (o --base-url, que manda y salta la cadena):
  - sk-sp-* (Token Plan) -> cadena TP en orden (R0 2026-11-09):
      https://token-plan.maas.qwencloudapi.com/compatible-mode/v1  (OFICIAL documentada,
        las bases TP NO llevan region ID — PRIMERA)
      https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1  (LEGACY,
        no aparece en doc; fallback)
      https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1  (otros workspaces)
  - sk-* / sk-ws-* (pay-as-you-go) ->
      https://maas.qwencloudapi.com/compatible-mode/v1
      https://ap-southeast-1.maas.qwencloudapi.com/compatible-mode/v1 (region SG oficial)
NOTA HONESTA: el fee document_parsing NO esta documentado para keys sk-sp- (Token Plan):
los tokens se consumen en Credits, pero el fee por pagina podria liquidarse via PAYG —
verificar en la factura (账单) tras la primera prueba (F2).

Reintentos: 429 -> espera 10 s, max 2 por base. 401/404/405 -> siguiente base.
Exit codes: 0 OK | 1 error de API/red (tras agotar cadena y reintentos) | 2 configuracion
(falta key/parametro, archivo invalido o >150 MB).
"""
import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

TP_CHAIN = [
    "https://token-plan.maas.qwencloudapi.com/compatible-mode/v1",
    "https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1",  # LEGACY
    "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
]
PAYG_CHAIN = [
    "https://maas.qwencloudapi.com/compatible-mode/v1",
    "https://ap-southeast-1.maas.qwencloudapi.com/compatible-mode/v1",
]
ENDPOINT = "/chat/completions"
MODEL_DEFAULT = "qwen3.8-flash"  # soportados: qwen3.8-max, qwen3.8-max-0902, qwen3.8-flash
MAX_BYTES = 150 * 1024 * 1024   # limite doc: 150 MB por archivo
REINTENTOS_429 = 2
ESPERA_429 = 10

KEY = None  # solo en memoria; nunca se imprime ni se guarda sin sanear


def diag(msg):
    """Diagnostico por stderr (nunca stdout, para no romper el JSON unico de --json)."""
    try:
        print(msg, file=sys.stderr)
    except Exception:  # noqa: BLE001
        pass


def resolver_key_y_cadena():
    """Devuelve (key, lista_bases) — Familia B: DASHSCOPE_API_KEY -> ANTHROPIC_AUTH_TOKEN
    -> auth.json; host por prefijo sk-sp- (TP) vs sk-*/sk-ws- (PAYG)."""
    candidates = []
    dash = (os.environ.get("DASHSCOPE_API_KEY") or "").strip()
    if dash:
        candidates.append(dash)
    anth = (os.environ.get("ANTHROPIC_AUTH_TOKEN") or "").strip()
    if anth:
        candidates.append(anth)
    auth_path = os.path.join(os.path.expanduser("~"), ".local", "share", "opencode", "auth.json")
    try:
        with open(auth_path, encoding="utf-8") as f:
            auth = json.load(f)
        for prov in ("alibaba-token-plan", "alibaba-token-plan-cn"):
            k = (auth.get(prov) or {}).get("key")
            if k:
                candidates.append(k.strip())
    except (OSError, ValueError):
        pass
    for k in candidates:
        if k.startswith("sk-sp-"):
            return k, TP_CHAIN
    for k in candidates:  # ninguna sk-sp-: aceptar la primera PAYG
        if k:
            return k, PAYG_CHAIN
    return None, None


def sanear_texto(txt):
    if isinstance(txt, str) and KEY and KEY in txt:
        return txt.replace(KEY, "[REDACTED_KEY]")
    return txt


def sanear(obj):
    if isinstance(obj, str):
        if KEY and KEY in obj:
            return "[REDACTED_KEY]"
        return obj
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k.lower() in ("authorization", "api_key", "apikey", "x-api-key") or (
                    isinstance(v, str) and KEY and KEY in v):
                out[k] = "[REDACTED_KEY]"
            else:
                out[k] = sanear(v)
        return out
    if isinstance(obj, list):
        return [sanear(x) for x in obj]
    return obj


def construir_parte_file(args):
    """(parte_file_dict, origen) para el content[type=file]."""
    if args.file:
        ruta = args.file
        if not os.path.isfile(ruta):
            diag(f"ERROR: --file no existe o no es archivo: {ruta}")
            sys.exit(2)
        size = os.path.getsize(ruta)
        if size > MAX_BYTES:
            diag(f"ERROR: PDF de {size/1048576:.1f} MB — el limite documentado es 150 MB.")
            diag(" hint: divide el PDF o subelo a una URL y usa --file-url.")
            sys.exit(2)
        with open(ruta, "rb") as f:
            cab = f.read(5)
            f.seek(0)
            raw = f.read()
        if not cab.startswith(b"%PDF"):
            diag("ERROR: el magic bytes no es %PDF — no parece un PDF real.")
            sys.exit(2)
        if size > 100 * 1024 * 1024:
            diag("[aviso] base64 infla ~1/3 el cuerpo (limite doc 150 MB): si falla el "
                 "upload, sube el archivo a una URL y usa --file-url.")
        b64 = base64.b64encode(raw).decode("ascii")
        return ({"type": "file",
                 "file": {"file_data": f"data:application/pdf;base64,{b64}",
                          "filename": os.path.basename(ruta)}}, os.path.basename(ruta))
    url = args.file_url
    if not url.startswith(("http://", "https://")):
        diag("ERROR: --file-url debe ser una URL http(s) descargable por el servidor.")
        sys.exit(2)
    return ({"type": "file", "file": {"file_url": url}}, url)


def construir_body(modelo, parte_file, pregunta):
    """Body POST /chat/completions con stream + include_tool_usage TOP-LEVEL (raw HTTP)."""
    return {
        "model": modelo,
        "messages": [{
            "role": "user",
            "content": [parte_file, {"type": "text", "text": pregunta}],
        }],
        "stream": True,
        "stream_options": {"include_usage": True},
        "include_tool_usage": True,
    }


EMITIR = None  # en modo humano: callable(delta) que imprime en vivo; en modo JSON: None


def leer_stream(resp):
    """Consume el SSE de /chat/completions. Devuelve (texto_acumulado, usage_dict).
    Si EMITIR esta definido, se llama con cada trozo (impresion en vivo modo humano)."""
    texto = []
    usage = {}
    for raw_line in resp:
        try:
            line = raw_line.decode("utf-8", "replace").strip()
        except Exception:  # noqa: BLE001
            continue
        if not line or not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            break
        try:
            chunk = json.loads(payload)
        except ValueError:
            continue
        if isinstance(chunk.get("usage"), dict):
            usage = chunk["usage"]
        for ch in (chunk.get("choices") or []):
            delta = (ch.get("delta") or {}).get("content")
            if isinstance(delta, str) and delta:
                texto.append(delta)
                if EMITIR:
                    try:
                        EMITIR(delta)
                    except Exception:  # noqa: BLE001
                        pass
    return "".join(texto), usage


def paginas_de(usage):
    """usage.x_tools.pdf_page_parser.count (requiere include_tool_usage:true). None si no hay."""
    if not isinstance(usage, dict):
        return None
    xt = usage.get("x_tools")
    if isinstance(xt, dict):
        v = xt.get("pdf_page_parser")
        if isinstance(v, dict) and isinstance(v.get("count"), int) and not isinstance(v.get("count"), bool):
            return v["count"]
    return None


def post_stream(base, key, body, timeout, intentos=1):
    """POST {base}/chat/completions consumiendo el stream. Devuelve
    (status, texto, usage, err|None). 429 reintenta con espera de 10 s; 401/404/405
    sube para que la cadena pruebe la siguiente base."""
    url = base.rstrip("/") + ENDPOINT
    data = json.dumps(body).encode("utf-8")
    for n in range(intentos):
        req = urllib.request.Request(url, data=data, method="POST", headers={
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "Authorization": "Bearer " + key,
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                texto, usage = leer_stream(r)
                return r.status, texto, usage, None
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")[:4000]
            try:
                parsed = json.loads(raw) if raw else {}
            except ValueError:
                parsed = {"raw": raw}
            err_msg = None
            if isinstance(parsed.get("error"), dict):
                err_msg = str(parsed["error"].get("message") or parsed["error"].get("code") or "")
            elif parsed.get("message"):
                err_msg = str(parsed.get("message"))
            else:
                err_msg = raw[:300]
            if e.code == 429 and n < intentos - 1:
                espera = ESPERA_429 * (n + 1)
                diag(f"[429 rate limit] base={base} esperando {espera}s (intento {n + 1}/{intentos})")
                time.sleep(espera)
                continue
            return e.code, None, None, sanear_texto(err_msg) or f"HTTP {e.code}"
        except Exception as e:  # noqa: BLE001  (URLError, timeout, DNS...)
            err = f"{type(e).__name__}: {e}"
            if n < intentos - 1:
                time.sleep(2)
                continue
            return None, None, None, sanear_texto(err)
    return None, None, None, "reintentos agotados"


def intentar_cadena(bases, key, body, timeout):
    """Recorre la cadena: 200 gana; 401/404/405 pasa a la siguiente; cualquier otro
    4xx/5xx es respuesta real y para. Devuelve (status, texto, usage, err, base_ok, usados)."""
    usados = []
    for base in bases:
        status, texto, usage, err = post_stream(base, key, body, timeout,
                                                intentos=REINTENTOS_429 + 1)
        usados.append((base, status, err))
        if status == 200:
            return status, texto, usage, err, base, usados
        if err is not None and status is None:
            diag(f"[red] fallo contra {base}: {err}")
            continue
        if status in (401, 404, 405):
            diag(f"[ruta/key] HTTP {status} en {base}: probando siguiente base candidata")
            continue
        return status, texto, usage, err, base, usados
    return status, texto, usage, err, None, usados


def main():
    global KEY
    ap = argparse.ArgumentParser(
        description="Lectura/entendimiento de PDF con QwenCloud (Chat Completions o "
                    "DashScope; NO Responses API)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--file", help="ruta local del PDF (<=150 MB; se codifica a base64 con filename)")
    g.add_argument("--file-url", help="URL publica del PDF (recomendado para archivos grandes)")
    ap.add_argument("--pregunta", default="Resume este documento",
                    help='pregunta sobre el PDF (default "Resume este documento")')
    ap.add_argument("--model", default=MODEL_DEFAULT,
                    help=f"modelo (default {MODEL_DEFAULT}; soportados: qwen3.8-max, "
                         "qwen3.8-max-0902, qwen3.8-flash)")
    ap.add_argument("--base-url", default=None, help="forzar base URL (manda sobre la cadena)")
    ap.add_argument("--timeout", type=int, default=300,
                    help="timeout HTTP en segundos (default 300: el primer token puede "
                         "tardar hasta 300 s con PDFs grandes)")
    ap.add_argument("--json", action="store_true", help="UN unico JSON en stdout (default: humano)")
    ap.add_argument("--out", default=None, help="guarda el resultado JSON (saneado) en la ruta dada")
    args = ap.parse_args()

    if not args.pregunta.strip():
        diag("ERROR: --pregunta vacia")
        sys.exit(2)
    if args.timeout < 1:
        diag("ERROR: --timeout debe ser >= 1")
        sys.exit(2)

    KEY, chain = resolver_key_y_cadena()
    if not KEY:
        diag("ERROR: sin API key (DASHSCOPE_API_KEY / ANTHROPIC_AUTH_TOKEN / auth.json)")
        diag("SUGERENCIA: crea la key en https://home.qwencloud.com/api-keys (Token Plan: prefijo sk-sp-)")
        sys.exit(2)
    bases = [args.base_url] if args.base_url else chain

    parte_file, origen = construir_parte_file(args)
    body = construir_body(args.model, parte_file, args.pregunta.strip())

    # En modo humano el stream se imprime en vivo por stdout; en modo JSON solo se acumula.
    global EMITIR
    if not args.json:
        def EMITIR(delta):
            sys.stdout.write(delta)
            sys.stdout.flush()
    else:
        EMITIR = None

    t0 = time.time()
    status, texto, usage, err, base_ok, usados = intentar_cadena(bases, KEY, body, args.timeout)
    latencia = round(time.time() - t0, 2)

    if status == 200:
        if args.json:
            res = {
                "ok": True,
                "model": args.model,
                "base": base_ok,
                "origen": origen,
                "answer": sanear_texto(texto or ""),
                "paginas": paginas_de(usage),
                "usage": {"input_tokens": (usage or {}).get("prompt_tokens") or (usage or {}).get("input_tokens"),
                          "output_tokens": (usage or {}).get("completion_tokens") or (usage or {}).get("output_tokens"),
                          "total_tokens": (usage or {}).get("total_tokens"),
                          "x_tools": (usage or {}).get("x_tools")},
                "seconds": latencia,
            }
            out_json = json.dumps(res, ensure_ascii=False)
            print(out_json)
            if args.out:
                guardar_out(args.out, res)
            sys.exit(0)
        # modo humano: el texto ya se emitió en vivo por stdout
        if texto:
            print()
        pag = paginas_de(usage)
        diag(f"[resumen] paginas={pag} tokens={(usage or {}).get('total_tokens')} "
             f"latencia={latencia}s base={base_ok}")
        if args.out:
            guardar_out(args.out, {"ok": True, "model": args.model, "origen": origen,
                                   "answer": texto, "paginas": pag, "usage": usage})
        sys.exit(0)

    err_obj = {"error": (err or f"http_{status}"), "http_status": status,
               "hint": hint_para(status, err)}
    if args.json:
        print(json.dumps({"ok": False, **err_obj,
                          "attempted": [{"base": b, "http": st, "err": sanear_texto(er) if er else None}
                                        for (b, st, er) in usados]}, ensure_ascii=False))
    else:
        diag(f"ERROR: {err_obj['error']} (HTTP {status}) — {err_obj['hint']}")
    if args.out:
        guardar_out(args.out, {"ok": False, **err_obj})
    sys.exit(1)


def hint_para(status, err):
    if status == 401:
        return "key invalida o key↔host incorrectos (sk-sp- ⇒ host token-plan)"
    if status == 429:
        return "rate limit agotado tras 2 reintentos con espera de 10 s — reduce el ritmo"
    if status == 400:
        return "parametro invalido (¿PDF >150 MB / >256 paginas / no es PDF?)"
    if err:
        return sanear_texto(str(err))[:200]
    return "ver la tabla ERRORES de SKILL.md"


def guardar_out(ruta, payload):
    """Guarda el resultado JSON saneado de la key. Crea el directorio si falta."""
    try:
        carpeta = os.path.dirname(os.path.abspath(ruta))
        if carpeta:
            os.makedirs(carpeta, exist_ok=True)
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(sanear(payload), f, ensure_ascii=False, indent=1)
        diag(f"[guardado] {ruta}")
    except OSError as e:
        diag(f"[aviso] no pude guardar --out: {e}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    main()
