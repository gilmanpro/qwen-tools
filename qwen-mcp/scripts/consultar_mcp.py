# -*- coding: utf-8 -*-
r"""Consulta un servidor MCP externo desde QwenCloud (Responses API + tool type:"mcp") — solo stdlib.

La plataforma QwenCloud conecta el modelo a un servidor MCP (Model Context Protocol) via
SSE: el modelo lista y llama las herramientas del servidor por si solo y devuelve la
respuesta. El servidor puede tener fee propio (del proveedor) ademas de los tokens.

CAUCION (R0 2026-11-09): la tool `mcp` NO figura en la allowlist de harness tools del
Token Plan (sk-sp-) — con esa key puede requerir pay-as-you-go. Verificar empiricamente.

Uso:
  py consultar_mcp.py --server-url "https://mcp.api-inference.modelscope.net/XXX/sse" --prompt "que hora es"
  py consultar_mcp.py --server-url URL --label fetch --description "trae URLs" --headers "Authorization=Bearer Tok3n" --json
  py consultar_mcp.py --server-url URL --prompt "..." --stream --timeout 180

El script:
  1. PREVALIDA: sin --server-url → exit 2 con JSON ok:false y hint — LA URL SSE LA
     APORTA EL USUARIO (de la plataforma donde esta el servidor, p. ej. ModelScope);
     este script NUNCA improvisa endpoints. No lanza ningun HTTP en ese caso.
  2. POST {base}/responses con
     {"model":..., "input":"<prompt>",
      "tools":[{"type":"mcp","server_protocol":"sse","server_label":...,
                "server_url":...,"server_description":...,"headers":{...}}]}
     (max 10 servers por request — este script manda 1).
  3. Recorre output[]: items mcp_call (name/arguments/output), message (texto final).
  4. --stream consume el SSE (response.output_text.delta / response.completed) —
     recomendado cuando el servidor MCP hace multiples interacciones.
  5. Salida por defecto HUMANA; con --json UN unico JSON en stdout. Diagnosticos stderr.
  6. NUNCA imprime la API key ni los valores de --headers (saneados).

Resolucion de key y base (Familia A — Responses API, patron identico al de las otras
skills qwen-*, p. ej. buscar_web.py de qwen-web-search):
  1) ~/.local/share/opencode/auth.json providers alibaba-token-plan / -cn (sk-sp-*) -> cadena TP.
  2) ANTHROPIC_AUTH_TOKEN si empieza por sk-sp- -> cadena TP.
  3) DASHSCOPE_API_KEY: sk-sp-* -> cadena TP; sk-* (pay-as-you-go) -> PAYG.
  4) --base-url manda sobre todo (usa solo esa base, sin cadena).
Cadena TP (orden R0 2026-11-09; gana la primera que responda en /responses sin 401/404/405):
  - https://token-plan.maas.qwencloudapi.com/compatible-mode/v1 (Token Plan OFICIAL documentada)
  - https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1 (LEGACY, fallback)
  - https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1 (otros workspaces)
PAYG: https://maas.qwencloudapi.com/compatible-mode/v1

Reintentos: 429 -> espera 10 s, max 2 por base. 401/404/405 -> siguiente base.
Exit codes: 0 OK | 1 error de API/red (tras agotar cadena y reintentos) | 2 configuracion
(sin --server-url, prompt vacio, headers mal formados, falta key).
"""
import argparse
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
PAYG_CHAIN = ["https://maas.qwencloudapi.com/compatible-mode/v1"]
ENDPOINT = "/responses"
MODEL_DEFAULT = "qwen3.8-flash"
REINTENTOS_429 = 2
ESPERA_429 = 10

KEY = None          # solo en memoria; nunca se imprime
SECRET_HEADERS = []  # valores de --headers a sangrar de cualquier salida


def diag(msg):
    try:
        print(msg, file=sys.stderr)
    except Exception:  # noqa: BLE001
        pass


def resolver_key_y_cadena():
    """(key, bases) — patron Familia A: auth.json sk-sp- -> ANTHROPIC_AUTH_TOKEN -> DASHSCOPE."""
    auth_path = os.path.join(os.path.expanduser("~"), ".local", "share", "opencode", "auth.json")
    try:
        with open(auth_path, encoding="utf-8") as f:
            auth = json.load(f)
    except (OSError, ValueError):
        auth = {}
    for prov in ("alibaba-token-plan", "alibaba-token-plan-cn"):
        k = (auth.get(prov) or {}).get("key")
        if k and k.strip().startswith("sk-sp-"):
            return k.strip(), TP_CHAIN
    anth = (os.environ.get("ANTHROPIC_AUTH_TOKEN") or "").strip()
    if anth.startswith("sk-sp-"):
        return anth, TP_CHAIN
    dash = (os.environ.get("DASHSCOPE_API_KEY") or "").strip()
    if dash:
        return dash, (TP_CHAIN if dash.startswith("sk-sp-") else PAYG_CHAIN)
    for prov in ("alibaba-token-plan", "alibaba-token-plan-cn"):
        k = (auth.get(prov) or {}).get("key")
        if k:
            return k.strip(), (TP_CHAIN if k.strip().startswith("sk-sp-") else PAYG_CHAIN)
    return None, None


def sanear_texto(txt):
    if isinstance(txt, str):
        if KEY and KEY in txt:
            txt = txt.replace(KEY, "[REDACTED_KEY]")
        for s in SECRET_HEADERS:
            if s and s in txt:
                txt = txt.replace(s, "[REDACTED_HEADER]")
        return txt
    return txt


def sanear(obj):
    if isinstance(obj, str):
        return sanear_texto(obj)
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k.lower() in ("authorization", "api_key", "apikey", "x-api-key") or (
                    isinstance(v, str) and ((KEY and KEY in v) or any(s and s in v for s in SECRET_HEADERS))):
                out[k] = "[REDACTED]"
            else:
                out[k] = sanear(v)
        return out
    if isinstance(obj, list):
        return [sanear(x) for x in obj]
    return obj


def parse_headers(spec):
    """'K=V,K2=V2' -> dict. Rechaza (exit 2) trozos sin '='."""
    if not spec:
        return None
    out = {}
    for trozo in spec.split(","):
        trozo = trozo.strip()
        if not trozo:
            continue
        if "=" not in trozo:
            diag(f"ERROR: --headers mal formado (falta '=' en {trozo!r}); esperado 'K=V,K2=V2'")
            sys.exit(2)
        k, v = trozo.split("=", 1)
        out[k.strip()] = v.strip()
        SECRET_HEADERS.append(v.strip())
    return out or None


def construir_body(modelo, prompt, tool):
    return {"model": modelo, "input": prompt, "tools": [tool]}


def construir_tool(args):
    tool = {
        "type": "mcp",
        "server_protocol": "sse",       # UNICO protocolo soportado (doc 2026-11-09)
        "server_label": args.label,
        "server_url": args.server_url,
    }
    if args.description:
        tool["server_description"] = args.description
    hdrs = parse_headers(args.headers)
    if hdrs:
        tool["headers"] = hdrs
    return tool


def parsear_respuesta(data):
    """(texto_final, mcp_calls) de un objeto response de /responses."""
    texto = ""
    calls = []
    for it in (data.get("output") or []):
        if not isinstance(it, dict):
            continue
        t = it.get("type")
        if t == "message":
            partes = it.get("content")
            if isinstance(partes, str):
                texto += partes
            elif isinstance(partes, list):
                for p in partes:
                    if isinstance(p, dict) and p.get("type") in ("output_text", "text") \
                            and isinstance(p.get("text"), str):
                        texto += p["text"]
        elif t in ("mcp_call", "mcp_list_tools", "mcp_approval_response"):
            calls.append({
                "type": t,
                "name": it.get("name"),
                "server_label": it.get("server_label"),
                "arguments": it.get("arguments"),
                "output": sanear_texto(str(it.get("output")))[:2000] if it.get("output") is not None else None,
            })
    return texto.strip(), calls


def post_respuestas(base, key, body, timeout, stream, intentos=1):
    """POST {base}/responses. Con stream=True consume SSE y reconstruye el objeto
    response final (response.completed). Devuelve (status, dict|None, err|None)."""
    url = base.rstrip("/") + ENDPOINT
    data = json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json", "Authorization": "Bearer " + key}
    if stream:
        headers["Accept"] = "text/event-stream"
        body = dict(body)
        body["stream"] = True
        data = json.dumps(body).encode("utf-8")
    else:
        headers["Accept"] = "application/json"
    last = (None, None, None)
    for n in range(intentos):
        req = urllib.request.Request(url, data=data, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                if not stream:
                    raw = r.read().decode("utf-8", "replace")
                    try:
                        return r.status, json.loads(raw), None
                    except ValueError:
                        return r.status, {"raw": raw[:4000]}, None
                evento_final = None
                trozos_texto = []
                for raw_line in r:
                    line = raw_line.decode("utf-8", "replace").strip()
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        ev = json.loads(payload)
                    except ValueError:
                        continue
                    et = ev.get("type")
                    if et == "response.output_text.delta" and isinstance(ev.get("delta"), str):
                        trozos_texto.append(ev["delta"])
                        try:
                            sys.stdout.write(ev["delta"])
                            sys.stdout.flush()
                        except Exception:  # noqa: BLE001
                            pass
                    elif et == "response.completed":
                        evento_final = ev.get("response")
                    elif et == "error":
                        return 400, ev, "error en stream"
                if isinstance(evento_final, dict) and trozos_texto and not (evento_final.get("output") or []):
                    evento_final.setdefault("output", []).append(
                        {"type": "message", "content": [{"type": "output_text", "text": "".join(trozos_texto)}]})
                return (r.status, evento_final or {}, None)
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            try:
                parsed = json.loads(raw) if raw else {}
            except ValueError:
                parsed = {"raw": raw[:4000]}
            last = (e.code, parsed, None)
            if e.code == 429 and n < intentos - 1:
                espera = ESPERA_429 * (n + 1)
                diag(f"[429 rate limit] base={base} esperando {espera}s (intento {n + 1}/{intentos})")
                time.sleep(espera)
                continue
            return last
        except Exception as e:  # noqa: BLE001
            last = (None, None, f"{type(e).__name__}: {e}")
            if n < intentos - 1:
                time.sleep(2)
                continue
            return last
    return last


def intentar_cadena(bases, key, body, timeout, stream):
    usados = []
    status, data, err = None, None, None
    base_ok = None
    for base in bases:
        status, data, err = post_respuestas(base, key, body, timeout, stream,
                                            intentos=REINTENTOS_429 + 1)
        usados.append((base, status, err))
        if status == 200:
            base_ok = base
            break
        if err is not None:
            diag(f"[red] fallo contra {base}: {err}")
            continue
        if status in (401, 404, 405):
            diag(f"[ruta/key] HTTP {status} en {base}: probando siguiente base candidata")
            continue
        base_ok = base
        break
    return status, data, err, base_ok, usados


def _blob_error(data):
    if not isinstance(data, dict):
        return None, None
    e = data.get("error")
    if isinstance(e, dict):
        return e.get("code") or e.get("type"), sanear_texto(str(e.get("message") or ""))[:300]
    if data.get("code") or data.get("message"):
        return data.get("code"), sanear_texto(str(data.get("message") or ""))[:300]
    if data.get("raw"):
        return None, sanear_texto(str(data["raw"]))[:300]
    return None, None


def main():
    global KEY
    ap = argparse.ArgumentParser(
        description="Consulta un servidor MCP (SSE) desde QwenCloud — Responses API, tool type:'mcp'")
    ap.add_argument("--server-url", default=None,
                    help="URL SSE del servidor MCP (OBLIGATORIA, la aporta el usuario — "
                         "nunca la improvises; p. ej. endpoint SSE de ModelScope)")
    ap.add_argument("--prompt", default=None, help="pregunta/input para el modelo (obligatorio)")
    ap.add_argument("--label", default="mcp-1",
                    help="server_label: nombre que identifica el servidor (default mcp-1)")
    ap.add_argument("--description", default=None,
                    help="server_description (recomendado: ayuda al modelo a elegir herramientas)")
    ap.add_argument("--headers", default=None,
                    help='headers extra "K=V,K2=V2" (p. ej. el token de la plataforma del server)')
    ap.add_argument("--model", default=MODEL_DEFAULT, help=f"modelo (default {MODEL_DEFAULT})")
    ap.add_argument("--stream", action="store_true",
                    help="SSE: imprime el texto en vivo (recomendado si el server hace multiples interacciones)")
    ap.add_argument("--base-url", default=None, help="forzar base URL (manda sobre la cadena)")
    ap.add_argument("--timeout", type=int, default=180, help="timeout HTTP en segundos (default 180)")
    ap.add_argument("--json", action="store_true", help="UN unico JSON en stdout (default: humano)")
    ap.add_argument("--out", default=None, help="guarda la respuesta JSON (saneada) en la ruta dada")
    args = ap.parse_args()

    # --- PREVALIDACION CRITICA: sin URL NO se lanza HTTP ni se inventa endpoint. ---
    if not args.server_url:
        msg = {"ok": False, "error": "falta_server_url",
               "hint": "la URL SSE la aporta el usuario — nunca improvises endpoints "
                       "(consiguela en la plataforma del servidor MCP, p. ej. Service "
                       "configuration de ModelScope)"}
        print(json.dumps(msg, ensure_ascii=False))
        diag("ERROR: falta --server-url (URL SSE del servidor MCP). Sin endpoint no hay "
             "HTTP: exit 2. El usuario debe proporcionar la URL.")
        sys.exit(2)
    if not args.server_url.startswith(("http://", "https://")):
        print(json.dumps({"ok": False, "error": "server_url_invalida",
                          "hint": "--server-url debe empezar por http:// o https://"},
                         ensure_ascii=False))
        sys.exit(2)
    if not args.prompt or not args.prompt.strip():
        print(json.dumps({"ok": False, "error": "falta_prompt",
                          "hint": "usa --prompt \"...\" con la consulta"}, ensure_ascii=False))
        sys.exit(2)
    if args.timeout < 1:
        diag("ERROR: --timeout debe ser >= 1")
        sys.exit(2)

    KEY, chain = resolver_key_y_cadena()
    if not KEY:
        diag("ERROR: sin API key (auth.json alibaba-token-plan / ANTHROPIC_AUTH_TOKEN / DASHSCOPE_API_KEY)")
        diag("SUGERENCIA: crea la key en https://home.qwencloud.com/api-keys")
        diag("NOTA: con sk-sp- (Token Plan) la tool mcp NO esta en la allowlist de harness "
             "documentada — puede requerir key pay-as-you-go (ver SKILL.md)")
        sys.exit(2)
    bases = [args.base_url] if args.base_url else chain

    tool = construir_tool(args)
    body = construir_body(args.model, args.prompt.strip(), tool)
    t0 = time.time()
    status, data, err, base_ok, usados = intentar_cadena(bases, KEY, body, args.timeout, args.stream)
    latencia = round(time.time() - t0, 2)

    if status == 200 and isinstance(data, dict):
        texto, calls = parsear_respuesta(data)
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        res = {
            "ok": True,
            "model": data.get("model") or args.model,
            "endpoint": base_ok,
            "server_label": args.label,
            "request_id": data.get("id"),
            "answer": sanear_texto(texto),
            "mcp_calls": sanear(calls),
            "usage": {"input_tokens": usage.get("input_tokens"),
                      "output_tokens": usage.get("output_tokens"),
                      "total_tokens": usage.get("total_tokens")},
            "seconds": latencia,
        }
        if args.out:
            guardar_out(args.out, {"http_status": status, "response": data})
        if args.json:
            print(json.dumps(res, ensure_ascii=False))
        elif not args.stream:
            print(sanear_texto(texto) or "(el modelo no devolvio texto final)")
            for i, c in enumerate(calls, 1):
                diag(f"[mcp {i}] {c['type']} {c.get('name') or ''} server={c.get('server_label')}")
            diag(f"[resumen] calls={len(calls)} tokens={res['usage']['total_tokens']} base={base_ok}")
        else:
            print()
            diag(f"[resumen] calls={len(calls)} tokens={res['usage']['total_tokens']} base={base_ok}")
        sys.exit(0)

    code, mensaje = _blob_error(data)
    if err is not None:
        mensaje = mensaje or err
    elif not mensaje:
        mensaje = f"HTTP {status} sin detalle en el payload"
    res = {"ok": False, "error": str(code or f"http_{status}"), "http_status": status,
           "mensaje": sanear_texto(str(mensaje)),
           "hint": "con sk-sp- (Token Plan) mcp NO esta en la allowlist harness documentada: "
                   "prueba con key pay-as-you-go; revisa que la URL SSE es el endpoint del "
                   "servidor y sus headers de auth",
           "attempted": [{"base": b, "http": st, "err": sanear_texto(er) if er else None}
                         for (b, st, er) in usados]}
    if args.out:
        guardar_out(args.out, {"http_status": status, "response": data})
    print(json.dumps(res, ensure_ascii=False))
    sys.exit(1)


def guardar_out(ruta, payload):
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
