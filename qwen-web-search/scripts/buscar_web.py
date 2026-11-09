# -*- coding: utf-8 -*-
"""Busqueda web con QwenCloud Token Plan (Responses API + tool web_search) — solo stdlib.

Uso:
  py buscar_web.py --query "clima en Madrid hoy" --json
  py buscar_web.py --query "precio acciones Alibaba" --model qwen3.8-max
  py buscar_web.py --query "X" --n 3 --answer short --max-searches-dia 10

REGLA DURA DEL HARNESS: la tool web_search SOLO se invoca via Responses API
(`POST {base}/responses`). Chat Completions NO dispara el harness de tools del
proveedor (las tools server-side quedan ignoradas).

El script:
  1. POST {BASE}/responses con {"model":..., "input":"<query>", "tools":[{"type":"web_search"}]}
  2. Recorre los output items:
       - web_search_call  -> action.query / action.queries / action.sources[].url
       - message (final)  -> texto de la respuesta (partes output_text)
  3. Lee usage.x_tools.web_search.count y todo el bloque usage.
     (Nota FAQ: `count` mide intencion de busqueda detectada, NO es base de facturacion;
     la facturacion real va en la factura del plan.)
  4. Imprime UN unico JSON en stdout con: ok, query, answer, sources, searches,
     usage, seconds, base, mode. Los diagnosticos van por stderr.
  5. NUNCA imprime la API key ni el body de la peticion.

Resolucion de key y base (precedencia):
  1) auth.json provider alibaba-token-plan(-cn) con key sk-sp-* -> cadena de bases TP.
  2) ANTHROPIC_AUTH_TOKEN si empieza por sk-sp- -> cadena de bases TP.
  3) DASHSCOPE_API_KEY (pay-as-you-go, sk-* no sk-sp) -> https://maas.qwencloudapi.com/compatible-mode/v1
  4) --base-url manda sobre todo lo anterior (una sola base, sin cadena).
Cadena TP (se prueban en orden; se usa la primera que responda en /responses sin
401/404/405). Se registra en el JSON de salida que base respondio:
  - https://token-plan.maas.qwencloudapi.com/compatible-mode/v1  (BASE DOCUMENTADA del
    Token Plan — docs regions/quickstart TP; las bases TP no llevan region ID)
  - https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1  (LEGACY /
    fallback empirico: 200 verificado 2026-10-07; NO aparece en la doc)
  - https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1  (401 con la key
    sk-sp- actual del workspace ap-southeast-1; queda para otras keys/workspaces)
(La antigua primera entrada ws-<ID-workspace>.../api/v1 se RETIRO de la cadena: 404
permanentemente verificado y sin respaldo documental.)

Control de consumo (fee de lista: $10 / 1.000 llamadas web_search en Singapur — la via
Responses se factura como estrategia `agent`; otras regiones $0.573411/1k):
  --n N: recorte client-side de sources[] (recortado a --n; 0 = todos). No cambia lo que
    cobra el servidor, solo el JSON local.
  --answer full|short|no (default full): full = texto integro del modelo; short = primer
    tramo ~600 chars + "[TRUNCADO]"; no = clave "answer" ausente en el JSON.
  --max-uses N: escribe {"type":"web_search","max_uses":N} dentro del tool. Es un param
    no listado en la doc Responses: si el endpoint responde 400 InvalidParameter
    mencionando max_uses, se reintenta UNA vez sin el campo (aviso por stderr). El
    limitante real de fees es --max-searches-dia.
  --max-searches-dia N (default 30; 0 = sin limite): presupuesto DIARIO compartido entre
    buscar_web.py (bucket "web"), buscar_imagen.py (bucket "imagen") y extraer_web.py
    (bucket "extractor", INFORMATIVO: no consume el limite). Contador unico en
    skills\\.qwen_uso_diario.json (resuelto como parents[2] de este script), formato
    {"fecha":"YYYY-MM-DD","web":N,"imagen":N,"extractor":N}. Si (web+imagen) >= N ANTES
    de lanzar, NO se hace el HTTP: JSON {"ok":false,"budget_exceeded":true,...} y exit 3.
    Tras una llamada con exito se suma usage.x_tools.web_search.count al bucket "web"
    (si falla la red NO se suma). Archivo ausente/corrupto se trata como 0 y se recrea.
    Reset: borrar el archivo (la fecha ademas reinicia sola al cambiar de dia).
  Nota: la via chat con enable_search NO existe en este script (solo Responses API).
    Las estrategias search_strategy turbo|max|agent|agent_max pertenecen a las vias
    Chat/DashScope/multimodal y se documentan en SKILL.md; aqui no aplican.

Exit codes: 0 OK | 1 error de API/red (tras agotar bases y reintentos) | 2 configuracion/uso
| 3 presupuesto diario agotado (budget_exceeded, sin peticion HTTP).
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
# fallback, despues cn-beijing.
WS_CHAIN = [
    "https://token-plan.maas.qwencloudapi.com/compatible-mode/v1",           # documentada TP
    "https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1",  # legacy/fallback (empirica 200)
    "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",    # otras keys/workspace (401 con sk-sp- actual)
]
PAYG_CHAIN = ["https://maas.qwencloudapi.com/compatible-mode/v1"]
ENDPOINT = "/responses"
MODEL_DEFAULT = "qwen3.8-flash"
REINTENTOS_429 = 2

# Contador diario compartido post-split: parents[2] = skills\\ (scripts -> skill -> skills).
RUTA_USO = str(Path(__file__).resolve().parents[2] / ".qwen_uso_diario.json")
DEFAULT_MAX_DIA = 30
HERRAMIENTAS = ("web_search",)  # claves de usage.x_tools que se facturan a este script


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
    # 1) auth.json sk-sp-
    for prov in ("alibaba-token-plan", "alibaba-token-plan-cn"):
        k = (auth.get(prov) or {}).get("key")
        if k and k.strip().startswith("sk-sp-"):
            return k.strip(), WS_CHAIN
    # 2) ANTHROPIC_AUTH_TOKEN sk-sp-
    anth = (os.environ.get("ANTHROPIC_AUTH_TOKEN") or "").strip()
    if anth.startswith("sk-sp-"):
        return anth, WS_CHAIN
    # 3) DASHSCOPE_API_KEY pay-as-you-go (acepta sk-sp- tambien, con su cadena)
    dash = (os.environ.get("DASHSCOPE_API_KEY") or "").strip()
    if dash:
        return dash, (WS_CHAIN if dash.startswith("sk-sp-") else PAYG_CHAIN)
    # ultima oportunidad: auth.json con cualquier key (p.ej. sk-ws-) -> PAYG
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


def parsear_web(data):
    """Extrae answer/sources/searches de un objeto response del API."""
    out = data.get("output") or []
    answer = ""
    sources, searches = [], []
    vistos_src, vistos_q = set(), set()
    for it in out:
        if not isinstance(it, dict):
            continue
        t = it.get("type")
        if t == "message":
            txt = _texto_de_item(it)
            if txt:
                answer += txt
        elif t == "web_search_call":
            act = it.get("action") or {}
            for clave in ("query", "queries"):
                v = act.get(clave)
                vals = v if isinstance(v, list) else ([v] if isinstance(v, str) else [])
                for q in vals:
                    if isinstance(q, str) and q and q not in vistos_q:
                        vistos_q.add(q)
                        searches.append(q)
            srcs = act.get("sources")
            if isinstance(srcs, list):
                for s in srcs:
                    url = s.get("url") if isinstance(s, dict) else (s if isinstance(s, str) else None)
                    if isinstance(url, str) and url and url not in vistos_src:
                        vistos_src.add(url)
                        sources.append(url)
    return answer.strip(), sources, searches


# ---------- Control de consumo (recortes y presupuesto diario) ----------

def recortar_lista(items, n):
    """Recorte client-side: con n>0 deja los primeros n; n=0 = todos. No afecta al fee."""
    if n and len(items) > n:
        return items[:n]
    return items


def recortar_texto(texto, modo, limite=600):
    """--answer/--analysis: full tal cual; short = ~limite chars + "[TRUNCADO]"; no = None."""
    if modo == "no":
        return None
    if modo == "short" and len(texto) > limite:
        return texto[:limite] + "[TRUNCADO]"
    return texto


def _entero_no_neg(v):
    """Entero >=0 tolerante (None/bool/negativo/cadena -> 0)."""
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 0


def leer_uso_hoy():
    """Lee skills\\.qwen_uso_diario.json con fecha local (datetime.date.today()). Si la
    fecha es de otro dia, o el archivo esta ausente/corrupto, reinicia a 0 en memoria.
    Solo lee: escribe unicamente tras una llamada con exito (asi un fallo de red no infla
    el contador). Buckets: web, imagen (comparten el limite de 30) y extractor
    (informativo, no bloquea)."""
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
    falla, avisa por stderr pero no rompe la salida (la busqueda ya se cobro igual)."""
    try:
        tmp = RUTA_USO + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(u, f, ensure_ascii=False)
        os.replace(tmp, RUTA_USO)
    except OSError as e:
        diag(f"[aviso] no pude actualizar el contador diario: {e}")


def sumar_counts(usage):
    """Suma usage.x_tools.<tool>.count de HERRAMIENTAS (busquedas realmente facturadas).
    Sin usage o sin x_tools (el modelo decidio no buscar) = 0."""
    n = 0
    if isinstance(usage, dict):
        xt = usage.get("x_tools")
        if isinstance(xt, dict):
            for h in HERRAMIENTAS:
                v = xt.get(h)
                n += _entero_no_neg(v.get("count") if isinstance(v, dict) else None)
    return n


def construir_body(modelo, query, max_uses=None):
    """Body POST /responses con la tool web_search. --max-uses va DENTRO del tool."""
    tool = {"type": "web_search"}
    if max_uses:
        tool["max_uses"] = max_uses
    return {"model": modelo, "input": query, "tools": [tool]}


def rechazo_max_uses(status, data):
    """True si es un 400 cuyo error menciona max_uses (param no soportado por el endpoint)."""
    if status != 400 or not isinstance(data, dict):
        return False
    e = data.get("error")
    if isinstance(e, dict):
        partes = [e.get("code"), e.get("type"), e.get("message")]
    else:
        partes = [data.get("code"), data.get("message")]
    blob = " ".join(str(p).lower() for p in partes if p)
    return "max_uses" in blob


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
    base; cualquier otro 4xx/5xx es respuesta real y para. Devuelve la ultima evidencia
    (status, data, err, base_ok, usados)."""
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
        # Cualquier otro 4xx/5xx (400 moderacion, 429 agotado, 5xx) es respuesta real: parar.
        base_ok = base
        break
    return status, data, err, base_ok, usados


def main():
    ap = argparse.ArgumentParser(description="Busqueda web con QwenCloud (Responses API web_search)")
    ap.add_argument("--query", required=True, help="consulta a buscar en la web")
    ap.add_argument("--model", default=MODEL_DEFAULT, help=f"modelo (default {MODEL_DEFAULT})")
    ap.add_argument("--base-url", default=None, help="forzar base URL (manda sobre la cadena)")
    ap.add_argument("--timeout", type=int, default=120, help="timeout HTTP en segundos")
    ap.add_argument("--json", action="store_true", help="salida JSON (por defecto ya emite JSON unico)")
    ap.add_argument("--n", type=int, default=5,
                    help="recorte client-side de sources[] (recortado a --n; 0 = todos; default 5)")
    ap.add_argument("--answer", choices=("full", "short", "no"), default="full",
                    help='texto del modelo: full (default) | short (~600 chars + "[TRUNCADO]") | no (clave answer ausente)')
    ap.add_argument("--max-uses", type=int, default=None,
                    help='anadir "max_uses":N dentro del tool (si el endpoint lo rechaza se reintenta sin el campo)')
    ap.add_argument("--max-searches-dia", type=int, default=DEFAULT_MAX_DIA,
                    help=f"presupuesto diario compartido web+imagen (default {DEFAULT_MAX_DIA}; 0 = sin limite)")
    args = ap.parse_args()

    if not args.query or not args.query.strip():
        diag("ERROR: falta --query")
        sys.exit(2)
    if args.n < 0:
        diag("ERROR: --n no puede ser negativo (usa 0 para todos)")
        sys.exit(2)
    if args.max_uses is not None and args.max_uses < 1:
        diag("ERROR: --max-uses debe ser >= 1")
        sys.exit(2)
    if args.max_searches_dia < 0:
        diag("ERROR: --max-searches-dia no puede ser negativo (usa 0 para sin limite)")
        sys.exit(2)

    # Presupuesto diario: se comprueba ANTES de lanzar cualquier HTTP.
    max_dia = args.max_searches_dia
    usado = leer_uso_hoy()
    if max_dia and (usado["web"] + usado["imagen"]) >= max_dia:
        res = {
            "ok": False,
            "budget_exceeded": True,
            "query": args.query,
            "mode": "web_search",
            "usado_hoy": usado,
            "max": max_dia,
            "hint": (f"presupuesto diario de {max_dia} busquedas agotado (web+imagen): no se lanzo "
                     f"la peticion. Espera al dia siguiente, sube --max-searches-dia o borra "
                     f"{RUTA_USO} para reiniciar"),
        }
        print(json.dumps(res, ensure_ascii=False))
        diag(f"ERROR: presupuesto diario agotado ({usado['web'] + usado['imagen']}/{max_dia})")
        sys.exit(3)

    key, chain = resolver_key_y_cadena()
    if not key:
        diag("ERROR: sin API key (auth.json alibaba-token-plan / ANTHROPIC_AUTH_TOKEN / DASHSCOPE_API_KEY)")
        diag("SUGERENCIA: crea la key en https://home.qwencloud.com/api-keys (Token Plan: prefijo sk-sp-)")
        sys.exit(2)
    bases = [args.base_url] if args.base_url else chain

    body = construir_body(args.model, args.query, args.max_uses)

    t0 = time.time()
    status, data, err, base_ok, usados = intentar_cadena(bases, key, body, args.timeout)

    # --max-uses es param no listado en Responses: si el endpoint lo rechaza (400
    # InvalidParameter mencionando max_uses), reintentar UNA vez sin el campo.
    if args.max_uses is not None and rechazo_max_uses(status, data):
        diag("max_uses ignorado por el endpoint; el limitante real es --max-searches-dia")
        body = construir_body(args.model, args.query, None)
        status, data, err, base_ok, usados = intentar_cadena(bases, key, body, args.timeout)

    seconds = round(time.time() - t0, 2)

    if status == 200 and isinstance(data, dict):
        answer, sources, searches = parsear_web(data)
        answer = recortar_texto(answer, args.answer)
        sources = recortar_lista(sources, args.n)
        # Contador diario: se suma SOLO tras exito (si fallo la red, no se infla).
        n_facturado = sumar_counts(data.get("usage"))
        if n_facturado:
            usado["web"] += n_facturado
            escribir_uso(usado)
            if max_dia and (usado["web"] + usado["imagen"]) >= max_dia:
                diag(f"[aviso] presupuesto diario alcanzado tras esta llamada: "
                    f"{usado['web'] + usado['imagen']}/{max_dia} (la siguiente ejecucion saldra con exit 3)")
        res = {
            "ok": True,
            "query": args.query,
            "answer": answer,
            "sources": sources,
            "searches": searches,
            "usage": data.get("usage"),
            "seconds": seconds,
            "base": base_ok,
            "mode": "web_search",
        }
        if args.answer == "no":
            res.pop("answer", None)
        print(json.dumps(res, ensure_ascii=False))
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
        "query": args.query,
        "answer": None,
        "sources": [],
        "searches": [],
        "usage": None,
        "seconds": seconds,
        "base": base_ok,
        "mode": "web_search",
        "http_status": status,
        "error": err_blob or ({"network": err} if err else {"unknown": True}),
        "attempted": intento_log,
    }
    if args.answer == "no":
        res.pop("answer", None)
    print(json.dumps(res, ensure_ascii=False))
    hint = ""
    if status == 401:
        hint = " (key invalida para esta base: revisa que la key sk-sp- corresponda al workspace)"
    elif status == 429:
        hint = " (rate limit: reintentar mas tarde)"
    diag(f"ERROR: busqueda falló HTTP {status}{hint}")
    sys.exit(1)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    main()
