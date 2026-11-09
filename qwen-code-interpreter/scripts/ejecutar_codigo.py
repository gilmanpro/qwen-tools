# -*- coding: utf-8 -*-
r"""Code Interpreter con QwenCloud Token Plan (Responses API + tool code_interpreter) — solo stdlib.

El modelo escribe Python, lo ejecuta en el sandbox REMOTO de QwenCloud y devuelve el stdout
(logs) junto a su respuesta final. El sandbox es EFIMERO (sin persistencia entre llamadas) y
la doc no documenta red ni lista de paquetes instalados → pide codigo STDLIB en el prompt.

Uso:
  py ejecutar_codigo.py --prompt "Calcula factorial(20) y los primos menores de 50"
  py ejecutar_codigo.py --prompt-file caso.txt --json
  py ejecutar_codigo.py --prompt "..." --timeout 180 --model qwen3.8-flash --out respuesta.json

El script:
  1. POST {BASE}/responses con
     {"model":..., "input":"<prompt>", "tools":[{"type":"code_interpreter"}]}
     SIN enable_thinking (en qwen3.8-flash los items "reasoning" salen igualmente —
     verificado 2026-10-07). El code_interpreter es EXCLUYENTE con function calling:
     no se mezclan otras tools en el body.
  2. Recorre los output items:
       - code_interpreter_call -> id / code (el Python ejecutado) / outputs[].logs / status
       - message (final)       -> texto de la respuesta (partes output_text)
  3. Ejecuciones facturadas: usage.x_tools.code_interpreter.count; fallback
     suma de usage.x_details[].plugins.code_interpreter.count (NO existe usage.plugins
     top-level — verificado 2026-10-07).
  4. Salida por defecto HUMANA (espanol); con --json UN unico JSON en stdout.
     Los diagnosticos van siempre por stderr.
  5. NUNCA imprime la API key (ni en errores); --out guarda el JSON crudo SANEEADO.

Resolucion de key y base (precedencia — patron identico al de las otras skills
 Responses API qwen-*, p. ej. buscar_web.py de qwen-web-search):
  1) ~/.local/share/opencode/auth.json providers alibaba-token-plan / -cn (key sk-sp-*) -> cadena TP.
  2) ANTHROPIC_AUTH_TOKEN si el valor empieza por sk-sp- -> cadena TP.
  3) DASHSCOPE_API_KEY: sk-sp-* -> cadena TP; sk-* (pay-as-you-go) -> PAYG.
  4) --base-url manda sobre todo lo anterior (usa solo esa base, sin cadena).
Cadena TP (orden R0 2026-11-09; gana la primera que responda en /responses sin 401/404/405):
  - https://token-plan.maas.qwencloudapi.com/compatible-mode/v1 (Token Plan OFICIAL
    documentada — las bases TP NO llevan region ID — va PRIMERA)
  - https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1 (LEGACY: 200
    verificado 2026-10-07 con code_interpreter, latencia ~21 s; no aparece en la doc,
    fallback marcado legacy)
  - https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1 (401 con la key
    sk-sp- actual; candidata para otros workspaces)
(La antigua primera entrada https://ws-<ID-workspace>.ap-southeast-1.maas.aliyuncs.com/api/v1
 se RETIRO de la cadena — RETIRADA, 404 permanente, nunca en cadena, sin respaldo
 documental — patron identico al de buscar_web.py de qwen-web-search.)

Reintentos: 429 rate limit -> espera 10 s, max 2 reintentos por base.
401/404/405 -> pasa a la siguiente base de la cadena.

Exit codes: 0 OK | 1 error de API/red (tras agotar bases y reintentos) | 2 configuracion/uso.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

# Cadena TP — orden R0 (2026-11-09): la base Token Plan OFICIAL documentada PRIMERO
# (las bases TP no llevan region ID); la legacy ap-southeast-1 (200 verificado
# 2026-10-07, no aparece en doc) como fallback marcado legacy; cn-beijing para otros
# workspaces. La antigua entrada ws-<ID-workspace>.../api/v1 se RETIRO de la cadena
# (RETIRADA — 404 permanente, nunca en cadena, sin respaldo documental).
WS_CHAIN = [
    "https://token-plan.maas.qwencloudapi.com/compatible-mode/v1",
    "https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1",  # LEGACY
    "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
]
PAYG_CHAIN = ["https://maas.qwencloudapi.com/compatible-mode/v1"]
ENDPOINT = "/responses"
MODEL_DEFAULT = "qwen3.8-flash"
REINTENTOS_429 = 2      # max 2 reintentos...
ESPERA_429 = 10         # ... con espera fija de 10 s (spec de la skill)

KEY = None  # solo en memoria; nunca se imprime ni se guarda sin sanear


def diag(msg):
    """Diagnostico por stderr (nunca stdout, para no romper el JSON unico de --json)."""
    try:
        print(msg, file=sys.stderr)
    except Exception:  # noqa: BLE001
        pass


def resolver_key_y_cadena():
    """Devuelve (key, lista_bases) segun la precedencia, o (None, None).
    Patron de buscar_web.py: auth.json sk-sp- -> ANTHROPIC_AUTH_TOKEN -> DASHSCOPE_API_KEY."""
    auth_path = os.path.join(os.path.expanduser("~"), ".local", "share", "opencode", "auth.json")
    try:
        with open(auth_path, encoding="utf-8") as f:
            auth = json.load(f)
    except (OSError, ValueError):
        auth = {}
    # 1) auth.json sk-sp-
    for prov in ("alibaba-token-plan", "alibaba-token-plan-cn"):
        k = (auth.get(prov) or {}).get("key")
        if k and k.strip().startswith("sk-sp-"):
            return k.strip(), WS_CHAIN
    # 2) ANTHROPIC_AUTH_TOKEN sk-sp-
    anth = (os.environ.get("ANTHROPIC_AUTH_TOKEN") or "").strip()
    if anth.startswith("sk-sp-"):
        return anth, WS_CHAIN
    # 3) DASHSCOPE_API_KEY (sk-sp- con cadena WS; sk-* pay-as-you-go con PAYG)
    dash = (os.environ.get("DASHSCOPE_API_KEY") or "").strip()
    if dash:
        return dash, (WS_CHAIN if dash.startswith("sk-sp-") else PAYG_CHAIN)
    # ultima oportunidad: auth.json con cualquier key (p.ej. sk-ws-) -> PAYG
    for prov in ("alibaba-token-plan", "alibaba-token-plan-cn"):
        k = (auth.get(prov) or {}).get("key")
        if k:
            return k.strip(), (WS_CHAIN if k.strip().startswith("sk-sp-") else PAYG_CHAIN)
    return None, None


def sanear_texto(txt):
    """Corta cualquier aparicion de la key en texto destined a stdout/archivo."""
    if isinstance(txt, str) and KEY and KEY in txt:
        return txt.replace(KEY, "[REDACTED_KEY]")
    return txt


def sanear(obj):
    """Sanea estructuras JSON: reemplaza la key y campos sensibles por nombre."""
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


def _texto_de_item(it):
    """Concatena el texto de un item message (partes output_text / text)."""
    partes = it.get("content")
    if isinstance(partes, str):
        return partes
    trozos = []
    if isinstance(partes, list):
        for p in partes:
            if not isinstance(p, dict):
                continue
            if p.get("type") in ("output_text", "text") and isinstance(p.get("text"), str):
                trozos.append(p["text"])
    return "".join(trozos)


def _logs_de_call(it):
    """Concatena los logs de un code_interpreter_call (outputs[].logs)."""
    trozos = []
    for o in (it.get("outputs") or []):
        if isinstance(o, dict) and isinstance(o.get("logs"), str):
            trozos.append(o["logs"])
        elif isinstance(o, str):
            trozos.append(o)
    return "\n".join(trozos)


def parsear_code(data):
    """Extrae (output_text, calls) de un objeto response.
    calls = [{id, code, logs, status}] en el orden de output[]."""
    out = data.get("output") or []
    texto = ""
    calls = []
    for it in out:
        if not isinstance(it, dict):
            continue
        t = it.get("type")
        if t == "message":
            txt = _texto_de_item(it)
            if txt:
                texto += txt
        elif t == "code_interpreter_call":
            calls.append({
                "id": it.get("id"),
                "code": it.get("code") if isinstance(it.get("code"), str) else "",
                "logs": _logs_de_call(it),
                "status": it.get("status"),
            })
    return texto.strip(), calls


def contar_ejecuciones(usage):
    """usage.x_tools.code_interpreter.count; fallback suma
    usage.x_details[].plugins.code_interpreter.count. None si no hay dato."""
    if not isinstance(usage, dict):
        return None
    xt = usage.get("x_tools")
    if isinstance(xt, dict):
        v = xt.get("code_interpreter")
        c = v.get("count") if isinstance(v, dict) else None
        if isinstance(c, int) and not isinstance(c, bool):
            return c
    xd = usage.get("x_details")
    if isinstance(xd, list):
        total = 0
        hay = False
        for d in xd:
            if isinstance(d, dict) and isinstance(d.get("plugins"), dict):
                v = d["plugins"].get("code_interpreter")
                c = v.get("count") if isinstance(v, dict) else None
                if isinstance(c, int) and not isinstance(c, bool):
                    total += c
                    hay = True
        if hay:
            return total
    return None


def construir_body(modelo, prompt):
    """Body POST /responses verificado (HTTP 200, 2026-10-07): sin enable_thinking y
    con UNA sola tool (code_interpreter es excluyente con function calling)."""
    return {"model": modelo, "input": prompt, "tools": [{"type": "code_interpreter"}]}


def request_id_de(headers, data):
    """Identificador trazable: body id > headers."""
    if isinstance(data, dict):
        rid = data.get("id") or data.get("request_id")
        if isinstance(rid, str) and rid:
            return rid
    for h in ("x-request-id", "request_id", "x-dashscope-request-id", "x-acs-request-id"):
        if headers.get(h):
            return headers.get(h)
    return None


def post_respuestas(base, key, body, timeout, intentos=1):
    """POST {base}/responses. Reintenta 429 con espera fija de 10 s (max 2).
    Devuelve (status, dict|None, headers, err|None)."""
    url = base.rstrip("/") + ENDPOINT
    data = json.dumps(body).encode("utf-8")
    last = (None, None, {}, None)
    for n in range(intentos):
        req = urllib.request.Request(url, data=data, method="POST", headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": "Bearer " + key,
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read().decode("utf-8", "replace")
                try:
                    parsed = json.loads(raw)
                except ValueError:
                    parsed = {"raw": raw[:4000]}
                return r.status, parsed, dict(r.headers), None
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            try:
                parsed = json.loads(raw) if raw else {}
            except ValueError:
                parsed = {"raw": raw[:4000]}
            last = (e.code, parsed, dict(e.headers or {}), None)
            if e.code == 429 and n < intentos - 1:
                espera = ESPERA_429 * (n + 1)
                diag(f"[429 rate limit] base={base} esperando {espera}s "
                     f"(intento {n + 1}/{intentos})")
                time.sleep(espera)
                continue
            return last
        except Exception as e:  # noqa: BLE001  (URLError, timeout, DNS...)
            last = (None, None, {}, f"{type(e).__name__}: {e}")
            if n < intentos - 1:
                time.sleep(2)
                continue
            return last
    return last


def intentar_cadena(bases, key, body, timeout):
    """Recorre la cadena de bases: 200 gana; 401/404/405 pasa a la siguiente base;
    cualquier otro 4xx/5xx es respuesta real y para. Devuelve
    (status, data, err, base_ok, usados=[(base, status, err)])."""
    status, data, err = None, None, None
    usados = []
    base_ok = None
    for base in bases:
        status, data, _hdrs, err = post_respuestas(base, key, body, timeout,
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
        # Cualquier otro 4xx/5xx (400 moderacion, 429 agotado, 5xx) es respuesta real: parar.
        base_ok = base
        break
    return status, data, err, base_ok, usados


def _blob_error(data):
    """(code, message) del payload de error, truncado y sin key."""
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


def tipo_error(status, err, code):
    """Clasificador del error para la clave error.tipo del JSON."""
    if err is not None:
        return "red"
    if status == 401:
        return "auth"
    if status == 429:
        return "rate_limit"
    if status == 404:
        return "endpoint_no_disponible"
    if code:
        return str(code)
    if status is not None:
        return f"http_{status}"
    return "desconocido"


def guardar_out(ruta, status, data):
    """Guarda el JSON crudo de respuesta saneado de la key. Crea el directorio si falta."""
    payload = sanear({"http_status": status, "response": data})
    carpeta = os.path.dirname(os.path.abspath(ruta))
    try:
        if carpeta:
            os.makedirs(carpeta, exist_ok=True)
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
        diag(f"[guardado] {ruta}")
    except OSError as e:
        diag(f"[aviso] no pude guardar --out: {e}")


def main():
    global KEY
    ap = argparse.ArgumentParser(
        description="Ejecuta Python en el sandbox Code Interpreter de QwenCloud (Responses API)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--prompt", help="instruccion/prompt directo (cuidado con quoting en cmd)")
    g.add_argument("--prompt-file", help="archivo .txt con el prompt (recomendado en Windows)")
    ap.add_argument("--model", default=MODEL_DEFAULT, help=f"modelo (default {MODEL_DEFAULT})")
    ap.add_argument("--base-url", default=None, help="forzar base URL (manda sobre la cadena)")
    ap.add_argument("--timeout", type=int, default=180,
                    help="timeout HTTP en segundos (default 180; la prueba real tardo ~21 s)")
    ap.add_argument("--json", action="store_true", help="UN unico JSON en stdout (default: humano)")
    ap.add_argument("--out", default=None, help="guarda el JSON crudo de respuesta (saneado) en la ruta dada")
    args = ap.parse_args()

    prompt = args.prompt
    if args.prompt_file:
        try:
            with open(args.prompt_file, encoding="utf-8") as f:
                prompt = f.read().strip()
        except OSError as e:
            diag(f"ERROR: no puedo leer --prompt-file: {e}")
            sys.exit(2)
    if not prompt or not prompt.strip():
        diag("ERROR: prompt vacio (usa --prompt o --prompt-file)")
        sys.exit(2)
    if args.timeout < 1:
        diag("ERROR: --timeout debe ser >= 1")
        sys.exit(2)

    KEY, chain = resolver_key_y_cadena()
    if not KEY:
        diag("ERROR: sin API key (auth.json alibaba-token-plan / ANTHROPIC_AUTH_TOKEN / DASHSCOPE_API_KEY)")
        diag("SUGERENCIA: crea la key en https://home.qwencloud.com/api-keys (Token Plan: prefijo sk-sp-)")
        sys.exit(2)
    bases = [args.base_url] if args.base_url else chain

    body = construir_body(args.model, prompt)
    t0 = time.time()
    status, data, err, base_ok, usados = intentar_cadena(bases, KEY, body, args.timeout)
    latencia = round(time.time() - t0, 2)

    if args.out:
        guardar_out(args.out, status, data)

    if status == 200 and isinstance(data, dict):
        output_text, calls = parsear_code(data)
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        ejecuciones = contar_ejecuciones(usage)
        if ejecuciones is None:
            ejecuciones = len(calls)
        rid = request_id_de({}, data)
        tok_in = usage.get("input_tokens")
        tok_out = usage.get("output_tokens")
        tok_tot = usage.get("total_tokens")

        if args.json:
            res = {
                "ok": True,
                "model": data.get("model") or args.model,
                "endpoint": base_ok,
                "request_id": rid,
                "output_text": sanear_texto(output_text),
                "calls": [{"code": sanear_texto(c["code"]),
                           "logs": sanear_texto(c["logs"]),
                           "status": c["status"]} for c in calls],
                "ejecuciones": ejecuciones,
                "usage": {"input_tokens": tok_in, "output_tokens": tok_out, "total_tokens": tok_tot},
                "latencia_s": latencia,
            }
            print(json.dumps(res, ensure_ascii=False))
            sys.exit(0)

        # Salida humana (espanol): texto final, luego un bloque por ejecucion y resumen.
        print(sanear_texto(output_text) or "(el modelo no devolvio texto final)")
        for i, c in enumerate(calls, 1):
            print(f"\n=== Codigo ejecutado (call {i}, {c['status']}) ===")
            print(sanear_texto(c["code"]))
            print("--- logs ---")
            print(sanear_texto(c["logs"]) or "(sin logs)")
        print(f"\nEjecuciones: {ejecuciones} | request_id: {rid} | "
              f"tokens in/out: {tok_in}/{tok_out}")
        sys.exit(0)

    # Error: JSON unico con ok=false si --json; si no, diagnosticos por stderr.
    code, mensaje = _blob_error(data)
    if err is not None:
        mensaje = mensaje or err
    elif not mensaje:
        mensaje = f"HTTP {status} sin detalle en el payload"
    err_obj = {"http_status": status, "tipo": tipo_error(status, err, code),
               "mensaje": sanear_texto(str(mensaje))}
    intento_log = [{"base": b, "http": st, "err": sanear_texto(er) if er else None}
                   for (b, st, er) in usados]
    if args.json:
        res = {"ok": False, "model": args.model, "endpoint": base_ok,
               "request_id": request_id_de({}, data) if isinstance(data, dict) else None,
               "output_text": None, "calls": [], "ejecuciones": 0,
               "usage": {"input_tokens": None, "output_tokens": None, "total_tokens": None},
               "latencia_s": latencia, "error": err_obj, "attempted": intento_log}
        print(json.dumps(res, ensure_ascii=False))
    else:
        diag(f"ERROR: {err_obj['tipo']} (HTTP {status}): {err_obj['mensaje']}")
        if status == 401:
            diag(" hint: key invalida para esta base — revisa que la sk-sp- corresponda al workspace")
        elif status == 429:
            diag(" hint: rate limit agotado tras 2 reintentos con espera de 10 s — reduce el ritmo")
        elif status in (404, 405):
            diag(" hint: la ruta /responses no existe en ninguna base de la cadena")
    diag("bases probadas: " + ", ".join(f"{b} -> {st or 'red'}" for (b, st, _e) in intento_log))
    sys.exit(1)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    main()
