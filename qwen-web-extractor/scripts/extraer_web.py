# -*- coding: utf-8 -*-
"""Web extractor con QwenCloud Token Plan (Responses API + tool web_extractor) — solo stdlib.

Uso:
  py extraer_web.py --url "https://example.com" --prompt "resume la pagina" --json
  py extraer_web.py --url https://a.com --url https://b.com          (1+ URLs, repetida)
  py extraer_web.py --url "https://a.com,https://b.com"              (o coma-separadas)
  py extraer_web.py --url "https://a.com" --out .tmp/extraccion.json

REGLA DURA DEL HARNESS: la tool web_extractor (y web_search que la acompana) SOLO se
invoca via Responses API (`POST {base}/responses`). Chat Completions NO dispara el
harness. NO requiere stream (la via Responses; las vias Chat/DashScope con
search_strategy:"agent_max" SI exigen stream — ver SKILL.md, no implementadas aqui).

El script:
  1. POST {BASE}/responses con {"model":..., "input": "<prompt + URLs>",
     "tools":[{"type":"web_search"},{"type":"web_extractor"}]}
     (--sin-web-search deja solo {"type":"web_extractor"}). El MODELO decide que paginas
     leer: las URLs del input son la referencia, no una descarga garantizada.
  2. Recorre los output items:
       - web_extractor_call -> goal (que se buscaba leer) + output (contenido extraido)
       - message (final)    -> texto de la respuesta (partes output_text)
  3. Lee usage.x_tools.web_extractor.count (y web_search.count) y todo el bloque usage.
  4. Imprime UN unico JSON en stdout con: ok, urls, prompt, answer, extracted, usage,
     seconds, base, mode, extracciones. Con --out ademas escribe el JSON en esa ruta.
     Los diagnosticos van por stderr.
  5. NUNCA imprime la API key ni el body de la peticion.

Limitaciones duras de la herramienta (doc oficial):
  - Solo paginas PUBLICAS: contenido tras autenticacion/paywall devuelve vacio.
  - Paginas muy grandes pueden ser TRUNCADAS antes de entrar al contexto.
  - Contenido dinamico renderizado solo por JAVASCRIPT puede no capturarse.
  - Extraction FAIL NO es error: el item web_extractor_call sale con goal/output vacio o
    parcial y el modelo responde con lo que tenga. Verificar exito inspeccionando
    `extracted[]` y usage.x_tools.web_extractor.count.

Resolucion de key y base (precedencia, identica a buscar_web.py):
  1) auth.json provider alibaba-token-plan(-cn) con key sk-sp-* -> cadena de bases TP.
  2) ANTHROPIC_AUTH_TOKEN si empieza por sk-sp- -> cadena TP.
  3) DASHSCOPE_API_KEY (pay-as-you-go) -> https://maas.qwencloudapi.com/compatible-mode/v1
  4) --base-url manda sobre todo (una sola base, sin cadena).
Cadena TP (primera que responda en /responses sin 401/404/405 gana; se registra en `base`):
  - https://token-plan.maas.qwencloudapi.com/compatible-mode/v1  (BASE DOCUMENTADA del
    Token Plan — docs regions/quickstart TP; las bases TP no llevan region ID)
  - https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1  (LEGACY /
    fallback empirico; NO aparece en la doc)
  - https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1  (otras keys/workspace)

Control de consumo:
  web_extractor esta GRATIS por tiempo limitado (fee 0). PERO suele disparar web_search
  interno, facturado a $10/1k (Singapur) si se lanza, y el contenido extraido SUBE los
  input tokens. Por eso el bucket "extractor" del contador diario compartido
  skills\\.qwen_uso_diario.json (parents[2] de este script) es INFORMATIVO: se suma tras
  cada exito usage.x_tools.web_extractor.count, pero NO consume ni bloquea el limite de
  30 busquedas web+imagen. Cuando la doc oficial anuncie fee para web_extractor, activar
  el bloqueo cambiando EXTRACTOR_BLOQUEA = True (y entonces comparte el tope via
  --max-searches-dia).
  --respuesta full|short|no (default full): texto del modelo; short ~600 chars +
  "[TRUNCADO]"; no = clave "answer" ausente.

Exit codes: 0 OK | 1 error de API/red (tras agotar bases y reintentos) | 2 configuracion/uso
(falta key, faltan --url, flag invalido). El 3 (presupuesto) no aplica: bucket informativo.
"""
import argparse
import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Cadena Token Plan (sk-sp-*): primero la documentada del Token Plan (docs regions /
# quickstart TP — las bases TP NO llevan region ID), despues la legacy empirica como
# fallback, despues cn-beijing. (Retirada ws-5oq3...: 404 verificado, sin respaldo documental.)
WS_CHAIN = [
    "https://token-plan.maas.qwencloudapi.com/compatible-mode/v1",           # documentada TP
    "https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1",  # legacy/fallback (empirica 200)
    "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",    # otras keys/workspace (401 con sk-sp- actual)
]
PAYG_CHAIN = ["https://maas.qwencloudapi.com/compatible-mode/v1"]
ENDPOINT = "/responses"
MODEL_DEFAULT = "qwen3.8-flash"
REINTENTOS_429 = 2
PROMPT_DEFAULT = "Extrae y resume el contenido de estas URLs"

# Contador diario compartido post-split: parents[2] = skills\\ (scripts -> skill -> skills).
RUTA_USO = str(Path(__file__).resolve().parents[2] / ".qwen_uso_diario.json")
HERRAMIENTAS_CONTADOR = ("web_extractor",)  # lo que suma al bucket "extractor"
EXTRACTOR_BLOQUEA = False  # True cuando la doc anuncie fee de web_extractor (ver docstring)
DEFAULT_MAX_DIA = 30       # solo relevante si EXTRACTOR_BLOQUEA = True


def diag(msg):
    """Diagnostico por stderr (nunca stdout, para no romper el JSON unico)."""
    try:
        print(msg, file=sys.stderr)
    except Exception:  # noqa: BLE001
        pass


def resolver_key_y_cadena():
    """Devuelve (key, lista_bases) segun la precedencia, o (None, None)."""
    auth_path = os.path.join(os.path.expanduser("~"), ".local", "share", "opencode", "auth.json")
    try:
        with open(auth_path, encoding="utf-8") as f:
            auth = json.load(f)
    except (OSError, ValueError):
        auth = {}
    for prov in ("alibaba-token-plan", "alibaba-token-plan-cn"):
        k = (auth.get(prov) or {}).get("key")
        if k and k.strip().startswith("sk-sp-"):
            return k.strip(), WS_CHAIN
    anth = (os.environ.get("ANTHROPIC_AUTH_TOKEN") or "").strip()
    if anth.startswith("sk-sp-"):
        return anth, WS_CHAIN
    dash = (os.environ.get("DASHSCOPE_API_KEY") or "").strip()
    if dash:
        return dash, (WS_CHAIN if dash.startswith("sk-sp-") else PAYG_CHAIN)
    for prov in ("alibaba-token-plan", "alibaba-token-plan-cn"):
        k = (auth.get(prov) or {}).get("key")
        if k:
            return k.strip(), (WS_CHAIN if k.strip().startswith("sk-sp-") else PAYG_CHAIN)
    return None, None


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


def parsear_extractor(data):
    """Extrae answer y extracted[] (items web_extractor_call: goal/output) de la response."""
    out = data.get("output") or []
    answer = ""
    extracted = []
    for it in out:
        if not isinstance(it, dict):
            continue
        t = it.get("type")
        if t == "message":
            txt = _texto_de_item(it)
            if txt:
                answer += txt
        elif t == "web_extractor_call":
            goal = it.get("goal")
            content = it.get("output")
            extracted.append({
                "goal": goal if isinstance(goal, str) else ("" if goal is None else str(goal)),
                "output": content if isinstance(content, str) else ("" if content is None else json.dumps(content, ensure_ascii=False)),
                "status": it.get("status"),
            })
    return answer.strip(), extracted


# ---------- Contador diario (bucket extractor INFORMATIVO) ----------

def _entero_no_neg(v):
    """Entero >=0 tolerante (None/bool/negativo/cadena -> 0)."""
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 0


def leer_uso_hoy():
    """Lee skills\\.qwen_uso_diario.json con fecha local. Otro dia / ausente / corrupto =
    0 en memoria (no escribe salvo tras exito). Buckets: web e imagen (limite compartido
    de 30, no los consume este script) y extractor (informativo)."""
    try:
        with open(RUTA_USO, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    hoy = datetime.date.today().isoformat()
    if not isinstance(data, dict) or data.get("fecha") != hoy:
        return {"fecha": hoy, "web": 0, "imagen": 0, "extractor": 0}
    return {"fecha": hoy,
            "web": _entero_no_neg(data.get("web")),
            "imagen": _entero_no_neg(data.get("imagen")),
            "extractor": _entero_no_neg(data.get("extractor"))}


def escribir_uso(u):
    """Reescribe skills\\.qwen_uso_diario.json de forma atomica (tmp + os.replace). Si
    falla, avisa por stderr pero no rompe la salida."""
    try:
        tmp = RUTA_USO + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(u, f, ensure_ascii=False)
        os.replace(tmp, RUTA_USO)
    except OSError as e:
        diag(f"[aviso] no pude actualizar el contador diario: {e}")


def sumar_counts(usage):
    """Suma usage.x_tools.<tool>.count de HERRAMIENTAS_CONTADOR (informativo)."""
    n = 0
    if isinstance(usage, dict):
        xt = usage.get("x_tools")
        if isinstance(xt, dict):
            for h in HERRAMIENTAS_CONTADOR:
                v = xt.get(h)
                n += _entero_no_neg(v.get("count") if isinstance(v, dict) else None)
    return n


def construir_body(modelo, urls, prompt, con_web_search=True):
    """Body POST /responses: tools web_extractor (normalmente acompanada de web_search).
    El input lleva el prompt + las URLs como referencia para el modelo."""
    tools = []
    if con_web_search:
        tools.append({"type": "web_search"})
    tools.append({"type": "web_extractor"})
    texto = (prompt or PROMPT_DEFAULT).strip()
    if urls:
        texto += "\n\nURLs de interes:\n" + "\n".join(urls)
    return {"model": modelo, "input": texto, "tools": tools}


def post_respuestas(base, key, body, timeout, intentos=1):
    """POST {base}/responses. Reintenta 429 con backoff. Devuelve (status, dict|None, err|None)."""
    url = base.rstrip("/") + ENDPOINT
    data = json.dumps(body).encode("utf-8")
    last = (None, None, None)
    for n in range(intentos):
        req = urllib.request.Request(url, data=data, method="POST", headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + key,
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, json.loads(r.read().decode("utf-8", "replace")), None
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            try:
                parsed = json.loads(raw) if raw else {}
            except ValueError:
                parsed = {"raw": raw[:400]}
            last = (e.code, parsed, None)
            if e.code == 429 and n < intentos - 1:
                espera = 5 * (n + 1)
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


def intentar_cadena(bases, key, body, timeout):
    """Recorre la cadena de bases con el body: 200 gana; 401/404/405 pasa a la siguiente
    base; cualquier otro 4xx/5xx es respuesta real y para."""
    status, data, err = None, None, None
    usados = []
    base_ok = None
    for base in bases:
        status, data, err = post_respuestas(base, key, body, timeout, intentos=REINTENTOS_429 + 1)
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


def emitir(res, out_path):
    """Imprime el JSON unico en stdout y, si --out, lo copia a esa ruta (dentro del proyecto)."""
    blob = json.dumps(res, ensure_ascii=False)
    print(blob)
    if out_path:
        try:
            carpeta = os.path.dirname(os.path.abspath(out_path))
            if carpeta:
                os.makedirs(carpeta, exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(blob)
        except OSError as e:
            diag(f"[aviso] no pude escribir --out: {e}")


def main():
    ap = argparse.ArgumentParser(
        description="Extraer/leer paginas web con QwenCloud (Responses API web_extractor)")
    ap.add_argument("--url", action="append", required=True, metavar="URL",
                    help="URL a leer; admite 1+ (repite --url a --url b o separa por comas)")
    ap.add_argument("--prompt", default=PROMPT_DEFAULT,
                    help="instruccion sobre que extraer (default: " + repr(PROMPT_DEFAULT) + ")")
    ap.add_argument("--model", default=MODEL_DEFAULT, help=f"modelo (default {MODEL_DEFAULT})")
    ap.add_argument("--base-url", default=None, help="forzar base URL (manda sobre la cadena)")
    ap.add_argument("--timeout", type=int, default=180,
                    help="timeout HTTP en segundos (la extraccion puede tardar; default 180)")
    ap.add_argument("--json", action="store_true", help="salida JSON (por defecto ya emite JSON unico)")
    ap.add_argument("--out", default=None,
                    help="ademas de stdout, escribe el JSON en esta ruta (dentro del proyecto)")
    ap.add_argument("--respuesta", choices=("full", "short", "no"), default="full",
                    help='texto del modelo (clave answer): full (default) | short (~600 chars + "[TRUNCADO]") | no (clave ausente)')
    ap.add_argument("--sin-web-search", action="store_true",
                    help="envia SOLO {\"type\":\"web_extractor\"} (por defecto va acompanada de web_search)")
    args = ap.parse_args()

    urls = []
    for grupo in (args.url or []):
        for parte in grupo.split(","):
            u = parte.strip()
            if u and u not in urls:
                urls.append(u)
    if not urls:
        diag("ERROR: indica al menos una --url (acepta --url a --url b o --url \"a,b\")")
        sys.exit(2)
    for u in urls:
        if not (u.startswith("http://") or u.startswith("https://")):
            diag(f"ERROR: URL invalida (debe empezar por http:// o https://): {u}")
            sys.exit(2)
    if args.timeout < 1:
        diag("ERROR: --timeout debe ser >= 1")
        sys.exit(2)

    key, chain = resolver_key_y_cadena()
    if not key:
        diag("ERROR: sin API key (auth.json alibaba-token-plan / ANTHROPIC_AUTH_TOKEN / DASHSCOPE_API_KEY)")
        diag("SUGERENCIA: crea la key en https://home.qwencloud.com/api-keys (Token Plan: prefijo sk-sp-)")
        sys.exit(2)
    bases = [args.base_url] if args.base_url else chain

    # Bloqueo de presupuesto SOLO si EXTRACTOR_BLOQUEA (hoy False: web_extractor gratis
    # por tiempo limitado y su bucket NO consume el limite web+imagen de 30).
    usado = leer_uso_hoy()
    if EXTRACTOR_BLOQUEA:
        max_dia = DEFAULT_MAX_DIA
        if max_dia and (usado["web"] + usado["imagen"] + usado["extractor"]) >= max_dia:
            res = {"ok": False, "budget_exceeded": True, "urls": urls, "mode": "web_extractor",
                   "usado_hoy": usado, "max": max_dia,
                   "hint": f"presupuesto diario agotado: borra {RUTA_USO} para reiniciar"}
            emitir(res, args.out)
            diag("ERROR: presupuesto diario agotado")
            sys.exit(3)

    body = construir_body(args.model, urls, args.prompt, not args.sin_web_search)
    t0 = time.time()
    status, data, err, base_ok, usados = intentar_cadena(bases, key, body, args.timeout)
    seconds = round(time.time() - t0, 2)

    if status == 200 and isinstance(data, dict):
        answer, extracted = parsear_extractor(data)
        if args.respuesta == "short" and answer and len(answer) > 600:
            answer = answer[:600] + "[TRUNCADO]"
        usage = data.get("usage")
        # Bucket extractor: INFORMATIVO — se suma tras exito, nunca bloquea.
        n_extraido = sumar_counts(usage)
        if n_extraido:
            usado["extractor"] += n_extraido
            escribir_uso(usado)
            if EXTRACTOR_BLOQUEA:
                diag(f"[aviso] contador extractor: {usado['extractor']} extracciones hoy (informativo)")
        xt = (usage or {}).get("x_tools") if isinstance(usage, dict) else None
        n_search = 0
        if isinstance(xt, dict):
            v = xt.get("web_search")
            n_search = _entero_no_neg(v.get("count") if isinstance(v, dict) else None)
        if n_search:
            diag(f"[aviso] esta llamada disparo {n_search} busqueda(s) web_search interna "
                 f"(fee $10/1k SG si se factura; NO cuenta al presupuesto local de 30)")
        res = {
            "ok": True,
            "urls": urls,
            "prompt": args.prompt,
            "answer": answer,
            "extracted": extracted,
            "extracciones": n_extraido,
            "usage": usage,
            "seconds": seconds,
            "base": base_ok,
            "mode": "web_extractor",
        }
        if args.respuesta == "no":
            res.pop("answer", None)
        emitir(res, args.out)
        if not extracted:
            diag("[aviso] la response no trajo items web_extractor_call: el modelo decidio no "
                 "leer ninguna pagina (o fallo silenciosamente). Revisa 'extracted' y 'usage'.")
        sys.exit(0)

    # Error: un unico JSON con ok=false. Sin key, sin body, solo diagnosticos sanos.
    err_blob = {}
    if isinstance(data, dict):
        e = data.get("error") or {}
        if isinstance(e, dict):
            err_blob = {"code": e.get("code"), "type": e.get("type"), "message": e.get("message")}
        elif data.get("code"):
            err_blob = {"code": data.get("code"), "message": data.get("message")}
    intento_log = [{"base": b, "http": st, "err": er} for (b, st, er) in usados]
    res = {
        "ok": False,
        "urls": urls,
        "prompt": args.prompt,
        "answer": None,
        "extracted": [],
        "extracciones": 0,
        "usage": None,
        "seconds": seconds,
        "base": base_ok,
        "mode": "web_extractor",
        "http_status": status,
        "error": err_blob or ({"network": err} if err else {"unknown": True}),
        "attempted": intento_log,
    }
    if args.respuesta == "no":
        res.pop("answer", None)
    emitir(res, args.out)
    hint = ""
    if status == 401:
        hint = " (key invalida para esta base: revisa que la key sk-sp- corresponda al workspace)"
    elif status == 429:
        hint = " (rate limit: reintentar mas tarde)"
    diag(f"ERROR: extraccion falló HTTP {status}{hint}")
    sys.exit(1)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    main()
