# -*- coding: utf-8 -*-
r"""PLANTILLA Function Calling con QwenCloud — loop multi-turno COMPLETO y ejecutable.

Demostracion end-to-end del patron: el modelo decide llamar una herramienta, TU la
ejecutas (aqui: clima SIMULADO, sin red), devuelves el resultado y el modelo redacta la
respuesta final. Es una PLANTILLA de demostracion: adaptala a tus herramientas reales.
(El smoke test vivo F2 la ejecuta con 1-2 llamadas baratas — gasta solo tokens.)

Uso:
  py plantilla_function_calling.py                       # demo por defecto (Madrid/Paris)
  py plantilla_function_calling.py --prompt "clima en Tokyo y Lima" --json
  py plantilla_function_calling.py --no-parallel         # una tool por turno
  py plantilla_function_calling.py --out .tmp\fc_demo.json

Flujo (via Chat Completions, la doc "Getting started" oficial):
  1. POST {base}/chat/completions con messages + tools (esquema anidado
     {"type":"function","function":{name,description,parameters}}).
  2. Si la respuesta trae choices[0].message.tool_calls: por CADA tool_call ejecutar la
     funcion local y anadir un mensaje {"role":"tool","tool_call_id":id,"content":result}.
  3. Repetir 1-2 mientras existan tool_calls (tope --max-turns) hasta la respuesta final.
  NOTAS de la doc: tool_choice "required" NO lo soporta Qwen (auto/none o forzar UNA;
  forzar exige enable_thinking:false); parallel_tool_calls default true (kimi-k3 lo
  ignora y puede devolver varias igualmente — iterar SIEMPRE todas); para el esquema
  plano de Responses API ver references/api-function-calling.md.

Resolucion de key y base (patron Familia A qwen-*, p. ej. buscar_web.py de
qwen-web-search — el endpoint aqui es /chat/completions, mismos hosts):
  1) auth.json (alibaba-token-plan / -cn, sk-sp-*) -> cadena TP
  2) ANTHROPIC_AUTH_TOKEN sk-sp- -> cadena TP
  3) DASHSCOPE_API_KEY: sk-sp- -> cadena TP; sk-* -> PAYG
  4) --base-url manda (sola esa base)
Cadena TP (orden R0 2026-11-09): token-plan.maas.qwencloudapi.com/compatible-mode/v1
  (OFICIAL documentada, sin region ID) -> token-plan.ap-southeast-1.maas.aliyuncs.com
  (LEGACY) -> token-plan.cn-beijing.maas.aliyuncs.com. PAYG: maas.qwencloudapi.com.

Salida: por defecto TRAZA legible del loop (cada decision, cada resultado de tool y la
respuesta final); con --json UN unico JSON en stdout. Diagnosticos por stderr.
NUNCA imprime la key (ni en errores); --out guarda la traza saneada.

Reintentos: 429 -> espera 10 s, max 2 por base. 401/404/405 -> siguiente base.
Exit codes: 0 OK | 1 error de API/red (tras agotar cadena y reintentos) | 2 configuracion.
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
ENDPOINT = "/chat/completions"
MODEL_DEFAULT = "qwen3.8-flash"
REINTENTOS_429 = 2
ESPERA_429 = 10

KEY = None  # solo en memoria; nunca se imprime

# ---------------------------------------------------------------- herramientas SIMULADAS
# En tu adaptacion: aqui va la llamada REAL (API, BD, archivo...). Ninguna tool de red.
def get_current_weather(arguments):
    """Clima SIMULADO determinista para la demo (funcion local, sin HTTP)."""
    ficticio = {
        "madrid": "soleado, 24°C, viento leve del oeste",
        "paris": "nublado, 15°C, lloviznas por la tarde",
        "tokyo": "despejado, 19°C, brisa del pacifico",
        "lima": "gris costero, 18°C, sin lluvia",
        "buenos aires": "lluvioso, 12°C, viento sur",
    }
    ciudad = str(arguments.get("location", "")).strip().lower()
    for k, v in ficticio.items():
        if k in ciudad or ciudad in k:
            return f"En {arguments.get('location')} hoy: {v}."
    return f"En {arguments.get('location')} hoy: variable, 20°C (estacion simulada sin datos)."


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_current_weather",
            "description": "Util cuando quieres comprobar el clima de una ciudad concreta.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "Ciudad o pais, por ejemplo Madrid o Nueva York.",
                    }
                },
                "required": ["location"],
            },
        },
    },
]
REGISTRO_LOCAL = {"get_current_weather": get_current_weather}


# ---------------------------------------------------------------- helpers
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
    if isinstance(txt, str) and KEY and KEY in txt:
        return txt.replace(KEY, "[REDACTED_KEY]")
    return txt


def sanear(obj):
    if isinstance(obj, str):
        return sanear_texto(obj)
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


def post_chat(base, key, body, timeout, intentos=1):
    """POST {base}/chat/completions (no-stream: los tool_calls llegan completos)."""
    url = base.rstrip("/") + ENDPOINT
    data = json.dumps(body).encode("utf-8")
    last = (None, None, None)
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
                    return r.status, json.loads(raw), None
                except ValueError:
                    return r.status, {"raw": raw[:4000]}, None
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


def llamar_modelo(bases, key, body, timeout, usados):
    """Cadena de bases para una llamada del loop. Devuelve (status, data, err, base_ok)."""
    status, data, err = None, None, None
    for base in bases:
        status, data, err = post_chat(base, key, body, timeout, intentos=REINTENTOS_429 + 1)
        usados.append((base, status, err))
        if status == 200:
            return status, data, err, base
        if err is not None:
            diag(f"[red] fallo contra {base}: {err}")
            continue
        if status in (401, 404, 405):
            diag(f"[ruta/key] HTTP {status} en {base}: probando siguiente base")
            continue
        return status, data, err, base
    return status, data, err, None


def main():
    global KEY
    ap = argparse.ArgumentParser(
        description="PLANTILLA Function Calling (loop clima SIMULADO multi-turno, Chat "
                    "Completions) — plantillas de demostracion, adaptala a tus tools")
    ap.add_argument("--prompt", default="Que tiempo hace hoy en Madrid y en Paris?",
                    help="pregunta del usuario para la demo")
    ap.add_argument("--model", default=MODEL_DEFAULT, help=f"modelo (default {MODEL_DEFAULT})")
    ap.add_argument("--max-turns", type=int, default=5,
                    help="tope de iteraciones del loop tool→modelo (default 5)")
    ap.add_argument("--no-parallel", action="store_true",
                    help="envia parallel_tool_calls:false (ojo: kimi-k3 lo ignora — "
                         "el loop SIEMPRE itera todos los tool_calls recibidos)")
    ap.add_argument("--base-url", default=None, help="forzar base URL (manda sobre la cadena)")
    ap.add_argument("--timeout", type=int, default=120, help="timeout HTTP por llamada (default 120)")
    ap.add_argument("--json", action="store_true", help="UN unico JSON con la traza en stdout")
    ap.add_argument("--out", default=None, help="guarda la traza JSON (saneada) en la ruta dada")
    args = ap.parse_args()

    if not args.prompt.strip():
        diag("ERROR: --prompt vacio")
        sys.exit(2)
    if args.max_turns < 1 or args.timeout < 1:
        diag("ERROR: --max-turns y --timeout deben ser >= 1")
        sys.exit(2)

    KEY, chain = resolver_key_y_cadena()
    if not KEY:
        diag("ERROR: sin API key (auth.json alibaba-token-plan / ANTHROPIC_AUTH_TOKEN / DASHSCOPE_API_KEY)")
        diag("SUGERENCIA: crea la key en https://home.qwencloud.com/api-keys")
        sys.exit(2)
    bases = [args.base_url] if args.base_url else chain

    messages = [{"role": "user", "content": args.prompt.strip()}]
    usados = []
    steps = []
    t0 = time.time()
    base_ok = None
    answer = None
    usage_total = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    for turno in range(1, args.max_turns + 1):
        body = {"model": args.model, "messages": messages, "tools": TOOLS}
        if args.no_parallel:
            body["parallel_tool_calls"] = False
        status, data, err, base_ok = llamar_modelo(bases, KEY, body, args.timeout, usados)
        if status != 200 or not isinstance(data, dict):
            msg = err or f"HTTP {status}"
            if isinstance(data, dict):
                e = data.get("error")
                if isinstance(e, dict):
                    msg = str(e.get("message") or e.get("code") or msg)[:300]
            res = {"ok": False, "error": sanear_texto(str(msg)), "http_status": status,
                   "turns": turno,
                   "attempted": [{"base": b, "http": st, "err": sanear_texto(er2) if er2 else None}
                                 for (b, st, er2) in usados]}
            if args.json:
                print(json.dumps(res, ensure_ascii=False))
            if args.out:
                guardar_out(args.out, res)
            if not args.json:
                diag(f"ERROR: {res['error']} (HTTP {status})")
            sys.exit(1)

        usage = data.get("usage") or {}
        for k in usage_total:
            if isinstance(usage.get(k), int):
                usage_total[k] += usage[k]
        choice = (data.get("choices") or [{}])[0]
        msg_a = choice.get("message") or {}
        content = msg_a.get("content")
        tool_calls = msg_a.get("tool_calls") or []

        # Reconstruir el mensaje assistant para el historial (content puede venir null).
        asst = {"role": "assistant", "content": content or ""}
        if tool_calls:
            asst["tool_calls"] = tool_calls
        messages.append(asst)

        if not tool_calls:
            answer = content or ""
            steps.append({"turn": turno, "kind": "respuesta_final", "text": sanear_texto(answer)})
            if not args.json:
                print(f"[turno {turno}] el modelo NO pidio herramientas — respuesta directa:")
                print(answer)
            break

        if not args.json:
            print(f"[turno {turno}] tool_calls: {len(tool_calls)}")
        for tc in tool_calls:
            fn = (tc.get("function") or {})
            nombre = fn.get("name")
            try:
                argumentos = json.loads(fn.get("arguments") or "{}")
            except ValueError:
                argumentos = {}
            if nombre in REGISTRO_LOCAL:
                resultado = REGISTRO_LOCAL[nombre](argumentos)
            else:
                resultado = f"ERROR: herramienta desconocida {nombre!r}"
            messages.append({"role": "tool", "tool_call_id": tc.get("id"), "content": resultado})
            steps.append({"turn": turno, "kind": "tool_call", "name": nombre,
                          "arguments": argumentos, "result": sanear_texto(str(resultado))})
            if not args.json:
                print(f"  -> {nombre}({argumentos}) = {resultado}")

    res = {
        "ok": answer is not None,
        "model": args.model,
        "base": base_ok,
        "turns": len({s["turn"] for s in steps}),
        "steps": sanear(steps),
        "answer": sanear_texto(answer or ""),
        "usage_acumulado": usage_total,
        "seconds": round(time.time() - t0, 2),
    }
    if args.out:
        guardar_out(args.out, res)
    if args.json:
        print(json.dumps(res, ensure_ascii=False))
    else:
        if answer is None:
            diag("[aviso] el loop alcanzo --max-turns sin respuesta final")
        print(f"\n=== RESPUESTA FINAL ===\n{answer or '(ninguna)'}")
        print(f"[turnos={res['turns']} tokens={usage_total['total_tokens']} "
              f"base={base_ok} {res['seconds']}s]", file=sys.stderr)
    sys.exit(0 if answer is not None else 1)


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
