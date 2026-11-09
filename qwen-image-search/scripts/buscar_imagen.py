# -*- coding: utf-8 -*-
"""Busqueda de imagenes con QwenCloud Token Plan (Responses API) — solo stdlib.

REGLA DURA DEL HARNESS: las tools web_search_image / image_search SOLO se invocan via
Responses API (`POST {base}/responses`); Chat Completions NO dispara el harness. Unicas
regiones con estas tools: Singapur y China North 2 (Beijing) — el Token Plan opera en
Singapur, de fabrica cumplida.

Dos modos (los flags de control se aplican identicos a ambos caminos):
  A) Texto -> imagenes (default). tools=[{"type":"web_search_image"}].
        py buscar_imagen.py --query "gato siames" --json
  B) Busqueda inversa (imagen -> imagenes similares). tools=[{"type":"image_search"}]
     con input = [{"role":"user","content":[{"type":"input_text","text":...},
                                            {"type":"input_image","image_url":...}]}].
     --image acepta URL publica, data URI base64 (data:image/png;base64,...) o ruta local de
     imagen (el script la convierte a data URI).
        py buscar_imagen.py --image "https://.../foto.jpg" --query "mobiliario similar" --json
        py buscar_imagen.py --image "data:image/png;base64,iVBOR..." --json

Parsea los output items:
  - web_search_image_call / image_search_call -> item["output"] es un STRING con un
    array JSON [{index,title,url}, ...]; se tolera que falte o no sea JSON.
  - message -> texto final (partes output_text).
  - arguments del call -> queries usadas (searches).

Salida: UN JSON unico en stdout con:
  ok, query, answer, sources, searches, usage, seconds, base, mode.
  mode = "web_search_image" (texto) | "image_search" (inversa).
  sources = lista de {index, title, url} de las imagenes encontradas.
Diagnostico por stderr. NUNCA se imprime la key ni el body.

Resolucion key/base identica a buscar_web.py (cadena TP: base documentada Token Plan →
legacy ap-southeast-1 → cn-beijing; fallback PAYG + --base-url manda).

Control de consumo (fee de lista: $8 / 1.000 llamadas web_search_image / image_search):
  --n N: recorte client-side de images[] (la lista sources del JSON; max doc: 100
    resultados; recortado a --n; 0 = todos). No cambia lo que cobra el servidor.
  --analysis full|short|no (default full): texto del analisis del modelo (clave existente
    "answer"): full = integro; short = primer tramo ~600 chars + "[TRUNCADO]"; no = clave
    "answer" ausente en el JSON.
  --max-uses N: escribe "max_uses":N dentro del tool ({"type":"web_search_image",...} o
    {"type":"image_search",...}). Param no listado en la doc Responses: si el endpoint
    responde 400 InvalidParameter mencionando max_uses, se reintenta UNA vez sin el campo
    (aviso por stderr). El limitante real de fees es --max-searches-dia.
  --max-searches-dia N (default 30; 0 = sin limite): presupuesto DIARIO compartido con
    buscar_web.py (y el bucket informativo "extractor" de extraer_web.py), contado en
    skills\\.qwen_uso_diario.json (resuelto como parents[2] de este script; formato
    {"fecha":"YYYY-MM-DD","web":N,"imagen":N,"extractor":N}). Si (web+imagen) >= N ANTES de lanzar, NO
    se hace el HTTP: JSON {"ok":false,"budget_exceeded":true,...} y exit 3. Tras una
    llamada con exito se suma usage.x_tools.web_search_image/image_search.count al bucket
    "imagen" (si falla la red NO se suma). Archivo ausente/corrupto = 0 y se recrea.
    Reset: borrar el archivo (la fecha ademas reinicia sola al cambiar de dia).

Pre-validacion gratuita de --image (solo busqueda inversa): ANTES de la key y de la API
  paga se verifica la entrada con HTTP gratuito contra la URL del usuario (HEAD, y si hace
  falta GET Range bytes=0-511) o inspeccionando el data URI / la ruta local (firma de
  PNG/JPEG/GIF/WEBP/BMP). Si la imagen es claramente invalida se aborta con exit 2 y JSON
  {"ok":false,"error":"imagen_no_valida","motivo":"...","hint":"..."} SIN gastar Credits y
  SIN sumar al contador. Casos ambiguos (anti-bot 401/403/429, sin respuesta, o content-type
  ausente y sin bytes) salen con motivo "url-no-verificable". --saltar-validacion omite SOLO
  este paso (nunca el presupuesto ni la key) y avisa por stderr. Orden en main(): args ->
  presupuesto -> pre-validacion -> key -> API.

Exit codes: 0 OK | 1 error de API/red | 2 configuracion/uso o imagen rechazada por la
  pre-validacion (imagen_no_valida) | 3 presupuesto diario agotado.
"""
import argparse
import base64
import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.parse
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

# Pre-validacion gratuita de --image (HEAD/GET contra la URL del usuario; NUNCA la API paga).
TIMEOUT_VALIDACION = 15
UA_VALIDACION = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                 "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
# Codigos HTTP que bloquean la verificacion (anti-bot/auth): se tratan como caso ambiguo.
HTTP_BLOQUEADOS = (401, 403, 429)

# Contador diario compartido post-split: parents[2] = skills\\ (scripts -> skill -> skills).
RUTA_USO = str(Path(__file__).resolve().parents[2] / ".qwen_uso_diario.json")
DEFAULT_MAX_DIA = 30
HERRAMIENTAS = ("web_search_image", "image_search")  # claves de usage.x_tools de este script

MIME_IMG = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".webp": "image/webp", ".gif": "image/gif", ".bmp": "image/bmp"}


def resolver_imagen_arg(valor):
    """--image puede ser URL (http/https), data URI o ruta local.

    En ruta local la lee y la convierte a data URI base64 (limite suave 20 MB).
    Devuelve (image_url, None) o (None, mensaje_error)."""
    v = valor.strip()
    if v.startswith("http://") or v.startswith("https://"):
        return v, None
    if v.startswith("data:"):
        return v, None
    if os.path.exists(v):
        try:
            with open(v, "rb") as f:
                raw = f.read()
        except OSError as e:
            return None, f"no puedo leer la imagen: {e}"
        if not raw:
            return None, "el archivo de imagen esta vacio"
        if len(raw) > 20 * 1024 * 1024:
            return None, "imagen > 20 MB (reducela antes de pasarla)"
        ext = os.path.splitext(v)[1].lower()
        mime = MIME_IMG.get(ext, "image/jpeg")
        return "data:" + mime + ";base64," + base64.b64encode(raw).decode("ascii"), None
    return None, "--image debe ser una URL http(s), un data URI o una ruta local existente"


# ---------- Pre-validacion gratuita del input de imagen (no toca la API paga) ----------

def magic_imagen_ok(cab):
    """True si los primeros bytes coinciden con una firma PNG/JPEG/GIF/WEBP/BMP."""
    if not cab or len(cab) < 2:
        return False
    if cab[:8] == b"\x89PNG\r\n\x1a\n":
        return True
    if cab[:3] == b"\xff\xd8\xff":
        return True
    if cab[:6] in (b"GIF87a", b"GIF89a"):
        return True
    if cab[:4] == b"RIFF" and cab[8:12] == b"WEBP":
        return True
    if cab[:2] == b"BM":
        return True
    return False


def _intentar_cabecera(url, metodo, timeout):
    """HEAD o GET Range contra la URL del usuario (HTTP gratuito, NUNCA la API paga).

    GET pide bytes=0-511 y lee SOLO esa cabecera del stream sin almacenar el resto (si el
    servidor ignora el Range y manda el archivo entero, leemos 512 bytes y cerramos).
    Devuelve dict con status, content_type, cab (bytes o None) y exc (True si no hubo
    respuesta HTTP: fallo de red/DNS)."""
    headers = {"User-Agent": UA_VALIDACION}
    if metodo == "GET":
        headers["Range"] = "bytes=0-511"
    req = urllib.request.Request(url, headers=headers, method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            cab = r.read(512) if metodo == "GET" else None
            return {"status": r.status, "content_type": r.headers.get("Content-Type"),
                    "cab": cab, "exc": False}
    except urllib.error.HTTPError as e:
        ct = e.headers.get("Content-Type") if e.headers else None
        return {"status": e.code, "content_type": ct, "cab": None, "exc": False}
    except Exception:  # noqa: BLE001
        return {"status": None, "content_type": None, "cab": None, "exc": True}


def prevalidar_url(url, timeout):
    """Pre-validacion gratuita de una URL de imagen: HEAD y, si hace falta, GET Range.

    Devuelve (ok, motivo, hint). Rechaza enlaces rotos (4xx/5xx), content-type que no es
    imagen y bytes sin firma de imagen; marca como 'url-no-verificable' los casos ambiguos
    (anti-bot 401/403/429, sin respuesta o content-type ausente y sin bytes) para que el
    usuario decida con --saltar-validacion."""
    head = _intentar_cabecera(url, "HEAD", timeout)
    # HEAD claro con content-type imagen -> aceptamos (HEAD no baja cuerpo, no hay magic).
    if not head["exc"] and head["status"] is not None and head["status"] < 400 and head["content_type"]:
        ct = head["content_type"].lower()
        if ct.startswith("image/"):
            return True, None, None
        return False, "no-es-imagen", f"el servidor declara content-type {head['content_type']}, no una imagen"
    # HEAD falla, responde >=400 o no trae content-type -> GET con Range 0-511 (primeros bytes).
    get = _intentar_cabecera(url, "GET", timeout)
    if not get["exc"] and get["status"] is not None and get["status"] < 400:
        if get["content_type"] and not get["content_type"].lower().startswith("image/"):
            return False, "no-es-imagen", f"el servidor declara content-type {get['content_type']}, no una imagen"
        if get["cab"]:
            if magic_imagen_ok(get["cab"]):
                return True, None, None
            return False, "magic-no-coincide", "el contenido no coincide con una firma de imagen (PNG/JPEG/GIF/WEBP/BMP)"
        return False, "url-no-verificable", "no se pudo leer el contenido: si estas seguro de que es una imagen valida, reejecuta con --saltar-validacion"
    if not get["exc"] and get["status"] is not None:
        if get["status"] in HTTP_BLOQUEADOS:
            return False, "url-no-verificable", f"el servidor bloqueo la verificacion (HTTP {get['status']}): si estas seguro de que es una imagen valida, reejecuta con --saltar-validacion"
        return False, "estado-http", f"la URL responde HTTP {get['status']}, no es descargable como imagen"
    # GET sin respuesta HTTP: reaprovecha una evidencia clara del HEAD (p. ej. 404) o es ambiguo.
    if not head["exc"] and head["status"] is not None and head["status"] >= 400 and head["status"] not in HTTP_BLOQUEADOS:
        return False, "estado-http", f"la URL responde HTTP {head['status']}, no es descargable como imagen"
    return False, "url-no-verificable", "no se pudo verificar la URL (sin respuesta): si estas seguro de que es una imagen valida, reejecuta con --saltar-validacion"


def prevalidar_data_uri(valor):
    """Pre-validacion de un data URI: MIME image/*, contenido decodificable y firma de imagen."""
    meta, _, datos = valor[len("data:"):].partition(",")
    mime = meta.split(";")[0].strip().lower()
    if not mime.startswith("image/"):
        return False, "no-es-imagen", f"el data URI declara MIME {mime or '(vacio)'}, no una imagen"
    if ";base64" in meta.lower():
        try:
            raw = base64.b64decode(datos, validate=True)
        except Exception:  # noqa: BLE001
            return False, "base64-invalido", "el data URI no es base64 valido"
    else:
        raw = urllib.parse.unquote_to_bytes(datos)
    if not raw or not magic_imagen_ok(raw[:12]):
        return False, "magic-no-coincide", "el contenido del data URI no coincide con una firma de imagen (PNG/JPEG/GIF/WEBP/BMP)"
    return True, None, None


def prevalidar_local(ruta):
    """Pre-validacion de una ruta local: existe y es archivo, <= 20 MB y firma de imagen en
    sus primeros 12 bytes (sin leer el archivo entero)."""
    if not os.path.isfile(ruta):
        return False, "archivo-invalido", "la ruta local no existe o no es un archivo"
    try:
        tam = os.path.getsize(ruta)
    except OSError as e:
        return False, "archivo-invalido", f"no puedo inspeccionar el archivo: {e}"
    if tam == 0:
        return False, "archivo-invalido", "el archivo de imagen esta vacio"
    if tam > 20 * 1024 * 1024:
        return False, "demasiado-grande", "imagen > 20 MB (reducela antes de pasarla)"
    try:
        with open(ruta, "rb") as f:
            cab = f.read(12)
    except OSError as e:
        return False, "archivo-invalido", f"no puedo leer la imagen: {e}"
    if not magic_imagen_ok(cab):
        return False, "magic-no-coincide", "el archivo no coincide con una firma de imagen (PNG/JPEG/GIF/WEBP/BMP)"
    return True, None, None


def prevalidar_imagen(valor, timeout):
    """Despacha la pre-validacion gratuita segun el tipo de --image (URL | data URI | local).
    No lanza la API paga ni toca el contador. Devuelve (ok, motivo, hint)."""
    v = valor.strip()
    if v.startswith("http://") or v.startswith("https://"):
        return prevalidar_url(v, timeout)
    if v.startswith("data:"):
        return prevalidar_data_uri(v)
    return prevalidar_local(v)


def diag(msg):
    try:
        print(msg, file=sys.stderr)
    except Exception:  # noqa: BLE001
        pass


def resolver_key_y_cadena():
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
    partes = it.get("content")
    if isinstance(partes, str):
        return partes
    trozos = []
    if isinstance(partes, list):
        for p in partes:
            if isinstance(p, dict) and p.get("type") in ("output_text", "text") and isinstance(p.get("text"), str):
                trozos.append(p["text"])
    return "".join(trozos)


def _parse_output_de_call(o):
    """El campo output de un *_search_call es un string JSON con array [{index,title,url}].

    Toleramos: None, string no-JSON, dict con clave images, u objeto ya parseado.
    Devuelve lista de dict {index,title,url} (normalizada)."""
    if not o:
        return []
    arr = None
    if isinstance(o, str):
        try:
            arr = json.loads(o)
        except ValueError:
            return []
    elif isinstance(o, (list, dict)):
        arr = o
    if isinstance(arr, dict):
        for k in ("images", "results", "data"):
            if isinstance(arr.get(k), list):
                arr = arr[k]
                break
        else:
            arr = [arr]
    if not isinstance(arr, list):
        return []
    norm = []
    for e in arr:
        if isinstance(e, dict):
            url = e.get("url") or e.get("image_url") or e.get("link")
            if isinstance(url, str) and url:
                norm.append({"index": e.get("index"), "title": e.get("title"), "url": url})
        elif isinstance(e, str) and e:
            norm.append({"index": None, "title": None, "url": e})
    return norm


def _queries_de_arguments(arguments):
    """El call trae 'arguments' como string JSON con {"queries":[...]}. Extrae queries."""
    if not arguments:
        return []
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except ValueError:
            return []
    if not isinstance(arguments, dict):
        return []
    v = arguments.get("queries")
    vals = v if isinstance(v, list) else ([v] if isinstance(v, str) else [])
    return [q for q in vals if isinstance(q, str) and q]


def parsear_imagen(data):
    out = data.get("output") or []
    answer = ""
    sources, searches = [], []
    vistos_u, vistos_q = set(), set()
    for it in out:
        if not isinstance(it, dict):
            continue
        t = it.get("type")
        if t == "message":
            txt = _texto_de_item(it)
            if txt:
                answer += txt
        elif t in ("web_search_image_call", "image_search_call"):
            for q in _queries_de_arguments(it.get("arguments")):
                if q not in vistos_q:
                    vistos_q.add(q)
                    searches.append(q)
            for img in _parse_output_de_call(it.get("output")):
                if img["url"] not in vistos_u:
                    vistos_u.add(img["url"])
                    sources.append(img)
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


def construir_body(modelo, query, image_url=None, max_uses=None):
    """Body POST /responses segun el modo (respeta la construccion original del script):
    con image_url -> tool image_search (busqueda inversa); sin ella -> web_search_image
    (texto->imagen). --max-uses va DENTRO del tool en AMBOS caminos.
    Devuelve (body, modo, query_logico)."""
    if image_url:
        tool = {"type": "image_search"}
        texto = query or "Find visually similar images"
        body = {"model": modelo,
                "input": [{"role": "user", "content": [
                    {"type": "input_text", "text": texto},
                    {"type": "input_image", "image_url": image_url}]}],
                "tools": [tool]}
        modo = "image_search"
        q_logico = query or texto
    else:
        tool = {"type": "web_search_image"}
        body = {"model": modelo, "input": query, "tools": [tool]}
        modo = "web_search_image"
        q_logico = query
    if max_uses:
        tool["max_uses"] = max_uses
    return body, modo, q_logico


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
        base_ok = base
        break
    return status, data, err, base_ok, usados


def main():
    ap = argparse.ArgumentParser(description="Busqueda de imagenes con QwenCloud (Responses API)")
    ap.add_argument("--query", help="texto de busqueda (obligatorio salvo con --image)")
    ap.add_argument("--image", help="URL o data URI base64 para busqueda inversa (image_search)")
    ap.add_argument("--model", default=MODEL_DEFAULT, help=f"modelo (default {MODEL_DEFAULT})")
    ap.add_argument("--base-url", default=None, help="forzar base URL (manda sobre la cadena)")
    ap.add_argument("--timeout", type=int, default=180, help="timeout HTTP en segundos")
    ap.add_argument("--json", action="store_true", help="salida JSON (por defecto ya emite JSON unico)")
    ap.add_argument("--n", type=int, default=5,
                    help="recorte client-side de images[] (max doc: 100; recortado a --n; 0 = todos; default 5)")
    ap.add_argument("--analysis", choices=("full", "short", "no"), default="full",
                    help='analisis del modelo (clave answer): full (default) | short (~600 chars + "[TRUNCADO]") | no (clave answer ausente)')
    ap.add_argument("--max-uses", type=int, default=None,
                    help='anadir "max_uses":N dentro del tool (si el endpoint lo rechaza se reintenta sin el campo)')
    ap.add_argument("--max-searches-dia", type=int, default=DEFAULT_MAX_DIA,
                    help=f"presupuesto diario compartido web+imagen (default {DEFAULT_MAX_DIA}; 0 = sin limite)")
    ap.add_argument("--saltar-validacion", action="store_true",
                    help="omite SOLO la pre-validacion gratuita de --image (no omite presupuesto ni key)")
    args = ap.parse_args()

    query = (args.query or "").strip()
    image = (args.image or "").strip()
    if not query and not image:
        diag("ERROR: indica --query (texto->imagen) o --image (busqueda inversa)")
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

    # Presupuesto diario: check ANTES de leer la imagen y de lanzar cualquier HTTP.
    max_dia = args.max_searches_dia
    usado = leer_uso_hoy()
    if max_dia and (usado["web"] + usado["imagen"]) >= max_dia:
        res = {
            "ok": False,
            "budget_exceeded": True,
            "query": query,
            "mode": "image_search" if image else "web_search_image",
            "usado_hoy": usado,
            "max": max_dia,
            "hint": (f"presupuesto diario de {max_dia} busquedas agotado (web+imagen): no se lanzo "
                     f"la peticion. Espera al dia siguiente, sube --max-searches-dia o borra "
                     f"{RUTA_USO} para reiniciar"),
        }
        print(json.dumps(res, ensure_ascii=False))
        diag(f"ERROR: presupuesto diario agotado ({usado['web'] + usado['imagen']}/{max_dia})")
        sys.exit(3)

    # Pre-validacion gratuita del input (solo busqueda inversa). Ningun HTTP a la API paga
    # y ninguna suma al contador si la imagen es claramente invalida: aborta con exit 2
    # (reutilizado como "configuracion/uso") y un JSON imagen_no_valida. Va DESPUES del
    # presupuesto (que sigue abortando primero) y ANTES de la key y de la API.
    if image and not args.saltar_validacion:
        ok_val, motivo, hint_val = prevalidar_imagen(image, TIMEOUT_VALIDACION)
        if not ok_val:
            res = {
                "ok": False,
                "error": "imagen_no_valida",
                "motivo": motivo,
                "hint": hint_val,
                "query": query,
                "mode": "image_search",
            }
            print(json.dumps(res, ensure_ascii=False))
            diag(f"ERROR: pre-validacion de imagen rechazada ({motivo})")
            sys.exit(2)
    elif image and args.saltar_validacion:
        diag("[aviso] validacion saltada por el usuario (--saltar-validacion)")

    image_url = None
    if image:
        image_url, err = resolver_imagen_arg(image)
        if err:
            diag("ERROR: " + err)
            sys.exit(2)

    body, modo, q_logico = construir_body(args.model, query, image_url, args.max_uses)

    key, chain = resolver_key_y_cadena()
    if not key:
        diag("ERROR: sin API key (auth.json alibaba-token-plan / ANTHROPIC_AUTH_TOKEN / DASHSCOPE_API_KEY)")
        diag("SUGERENCIA: crea la key en https://home.qwencloud.com/api-keys (Token Plan: prefijo sk-sp-)")
        sys.exit(2)
    bases = [args.base_url] if args.base_url else chain

    t0 = time.time()
    status, data, err, base_ok, usados = intentar_cadena(bases, key, body, args.timeout)

    # --max-uses es param no listado en Responses: si el endpoint lo rechaza (400
    # InvalidParameter mencionando max_uses), reintentar UNA vez sin el campo.
    if args.max_uses is not None and rechazo_max_uses(status, data):
        diag("max_uses ignorado por el endpoint; el limitante real es --max-searches-dia")
        body, modo, q_logico = construir_body(args.model, query, image_url, None)
        status, data, err, base_ok, usados = intentar_cadena(bases, key, body, args.timeout)

    seconds = round(time.time() - t0, 2)

    if status == 200 and isinstance(data, dict):
        answer, sources, searches = parsear_imagen(data)
        answer = recortar_texto(answer, args.analysis)
        sources = recortar_lista(sources, args.n)
        # Contador diario: se suma SOLO tras exito (si fallo la red, no se infla).
        n_facturado = sumar_counts(data.get("usage"))
        if n_facturado:
            usado["imagen"] += n_facturado
            escribir_uso(usado)
            if max_dia and (usado["web"] + usado["imagen"]) >= max_dia:
                diag(f"[aviso] presupuesto diario alcanzado tras esta llamada: "
                    f"{usado['web'] + usado['imagen']}/{max_dia} (la siguiente ejecucion saldra con exit 3)")
        res = {
            "ok": True,
            "query": q_logico,
            "answer": answer,
            "sources": sources,
            "searches": searches,
            "usage": data.get("usage"),
            "seconds": seconds,
            "base": base_ok,
            "mode": modo,
        }
        if args.analysis == "no":
            res.pop("answer", None)
        print(json.dumps(res, ensure_ascii=False))
        sys.exit(0)

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
        "query": q_logico,
        "answer": None,
        "sources": [],
        "searches": [],
        "usage": None,
        "seconds": seconds,
        "base": base_ok,
        "mode": modo,
        "http_status": status,
        "error": err_blob or ({"network": err} if err else {"unknown": True}),
        "attempted": intento_log,
    }
    if args.analysis == "no":
        res.pop("answer", None)
    print(json.dumps(res, ensure_ascii=False))
    hint = ""
    if status == 401:
        hint = " (key invalida para esta base: revisa que la key sk-sp- corresponda al workspace)"
    elif status == 429:
        hint = " (rate limit: reintentar mas tarde)"
    diag(f"ERROR: busqueda de imagen falló HTTP {status}{hint}")
    sys.exit(1)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    main()
