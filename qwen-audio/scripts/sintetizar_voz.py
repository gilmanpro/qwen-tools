# -*- coding: utf-8 -*-
"""Sintetizador de voz QwenCloud (qwen-audio-3.0-tts-plus) — solo stdlib.

Dos vias:
  * WebSocket (DEFAULT, verificada empiricamente): protocolo run-task / continue-task /
    finish-task de DashScope Inference API, streaming duplex. Cliente minimo con stdlib
    (socket, ssl, base64, hashlib, struct, uuid, os).
  * HTTP one-shot (--http): via DOCUMENTADA para Token Plan desde 2026-11 (doc TP best
    practices speech-synthesis): POST {base}/services/audio/tts/SpeechSynthesizer con
    {"model","input":{"text","voice","format","sample_rate"}} → output.audio.url
    (expira en 24 h) → descarga automatica. El error historico "current user api does not
    support http call" correspondia a otras vias HTTP (multimodal/compatible), no a este
    endpoint. Si --http falla en vivo (F2), usa el default WS.

Uso:
  py sintetizar_voz.py --text "Hello world" --output voz.mp3
  py sintetizar_voz.py --text-file guion.txt --voice longanlufeng --format mp3 --output out.mp3
  py sintetizar_voz.py --text "Hola" --output voz.wav --http   # one-shot REST

Voces de sistema verificadas en Token Plan: longanlingxin (F, default) y longanlufeng (M)
— chino/ingles y ESPANOL verificado empiricamente. La doc TP menciona como default
"longanhuan_v3.6" pero esa voz pertenece a 3.0-tts-flash (fuera de allowlist TP):
discrepancia documental — NO se afirma usable, probar antes de usarla.

API key (en orden de busqueda):
  1. env DASHSCOPE_API_KEY
  2. env ANTHROPIC_AUTH_TOKEN (convencion Token Plan)
  3. ~/.local/share/opencode/auth.json (providers alibaba-token-plan / -cn)
Bases (las Token Plan NO llevan region ID; pay-as-you-go con region segun doc de regions):
  sk-sp-*  WS: wss://token-plan.maas.qwencloudapi.com/api-ws/v1/inference  (si el handshake
           falla, reintenta UNA vez con el host pay-as-you-go)
         REST: https://token-plan.maas.qwencloudapi.com/api/v1
  sk-*/sk-ws-*  WS: wss://ap-southeast-1.maas.qwencloudapi.com/api-ws/v1/inference
                REST: https://ap-southeast-1.maas.qwencloudapi.com/api/v1
Exit codes: 0 OK | 1 error de API/WS/HTTP | 2 configuracion/uso.
Skill hija del split multimedia (2026-11-09).
"""
import argparse
import base64
import hashlib
import json
import os
import socket
import ssl
import struct
import sys
import time
import urllib.error
import urllib.request
import uuid

WSS_PAYG = "wss://ap-southeast-1.maas.qwencloudapi.com/api-ws/v1/inference"
WSS_TOKEN_PLAN = "wss://token-plan.maas.qwencloudapi.com/api-ws/v1/inference"
BASE_REST_TOKEN_PLAN = "https://token-plan.maas.qwencloudapi.com/api/v1"
BASE_REST_PAYG = "https://ap-southeast-1.maas.qwencloudapi.com/api/v1"
ENDPOINT_TTS_HTTP = "/services/audio/tts/SpeechSynthesizer"
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
CHUNK_MAX = 15000          # <=20000 chars por continue-task (CJK cuenta 2 -> margen)
MODELO_DEFAULT = "qwen-audio-3.0-tts-plus"
VOCES_SISTEMA = ("longanlingxin", "longanlufeng")
FORMATOS = ("mp3", "wav", "pcm", "opus")
SAMPLE_RATES = (8000, 16000, 22050, 24000, 44100, 48000)


class HandshakeError(Exception):
    def __init__(self, http_code, detalle):
        super().__init__(detalle)
        self.http_code = http_code


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


# ---------- cliente WebSocket minimo (stdlib) ----------

def _recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("conexion cerrada por el servidor (EOF)")
        buf += chunk
    return buf


def ws_escribir_frame(sock, opcode, payload):
    """El cliente SIEMPRE enmascara (RFC 6455)."""
    hdr = bytearray([0x80 | opcode])  # FIN=1
    n = len(payload)
    mask = os.urandom(4)
    if n < 126:
        hdr.append(0x80 | n)
    elif n < 65536:
        hdr.append(0x80 | 126)
        hdr += struct.pack("!H", n)
    else:
        hdr.append(0x80 | 127)
        hdr += struct.pack("!Q", n)
    hdr += mask
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    sock.sendall(bytes(hdr) + masked)


def ws_leer_frame(sock):
    """Devuelve (fin, opcode, payload). El servidor no enmascara (se tolera si lo hace)."""
    b0, b1 = _recv_exact(sock, 2)
    fin = bool(b0 & 0x80)
    opcode = b0 & 0x0F
    masked = bool(b1 & 0x80)
    ln = b1 & 0x7F
    if ln == 126:
        ln = struct.unpack("!H", _recv_exact(sock, 2))[0]
    elif ln == 127:
        ln = struct.unpack("!Q", _recv_exact(sock, 8))[0]
    maskkey = _recv_exact(sock, 4) if masked else None
    payload = _recv_exact(sock, ln) if ln else b""
    if maskkey:
        payload = bytes(b ^ maskkey[i % 4] for i, b in enumerate(payload))
    return fin, opcode, payload


def parsear_wss_url(url):
    scheme, _, rest = url.partition("://")
    tls = scheme in ("wss", "https")
    hostpart, _, path = rest.partition("/")
    path = "/" + path if path else "/"
    if hostpart.startswith("["):  # IPv6
        host, _, tail = hostpart.partition("]")
        host = host[1:]
        port = int(tail.split(":")[1]) if ":" in tail else (443 if tls else 80)
    elif ":" in hostpart:
        host, p = hostpart.rsplit(":", 1)
        port = int(p)
    else:
        host, port = hostpart, (443 if tls else 80)
    return tls, host, port, path


def normalizar_base_url(url):
    """Acepta wss://... completo, o https://host(/api/v1) y lo lleva al endpoint de inferencia."""
    u = url.strip().rstrip("/")
    if u.startswith("https://"):
        u = "wss://" + u[len("https://"):]
    elif u.startswith("http://"):
        u = "ws://" + u[len("http://"):]
    if "/api/v1" in u:
        u = u.replace("/api/v1", "/api-ws/v1/inference")
    else:
        scheme, _, rest = u.partition("://")
        if "/" not in rest:
            u = u + "/api-ws/v1/inference"
    return u


def ws_conectar(wss_url, key, timeout):
    """Handshake HTTP/1.1 -> 101 Switching Protocols sobre TLS."""
    tls, host, port, path = parsear_wss_url(wss_url)
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
    except OSError as e:
        raise HandshakeError(0, f"conexion TCP con {host}:{port} fallo: {e}")
    if tls:
        try:
            ctx = ssl.create_default_context()
            sock = ctx.wrap_socket(sock, server_hostname=host)
        except OSError as e:
            try:
                sock.close()
            except OSError:
                pass
            raise HandshakeError(0, f"TLS con {host} fallo: {e}")
    ws_key = base64.b64encode(os.urandom(16)).decode("ascii")
    peticion = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {ws_key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        f"Authorization: Bearer {key}\r\n"
        "\r\n"
    )
    sock.sendall(peticion.encode("ascii"))
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            break
        buf += chunk
    cabeza, _, resto = buf.partition(b"\r\n\r\n")
    texto = cabeza.decode("latin-1", "replace")
    linea = texto.split("\r\n", 1)[0]
    partes = linea.split(" ", 2)
    code = int(partes[1]) if len(partes) >= 2 and partes[1].isdigit() else 0
    if code != 101:
        cuerpo = resto.decode("utf-8", "replace")[:300] if resto else ""
        try:
            sock.close()
        except OSError:
            pass
        raise HandshakeError(code, f"handshake WS no devolvio 101: '{linea}' {cuerpo}".strip())
    acept = ""
    for ln_ in texto.split("\r\n")[1:]:
        if ln_.lower().startswith("sec-websocket-accept:"):
            acept = ln_.split(":", 1)[1].strip()
    esperado = base64.b64encode(hashlib.sha1((ws_key + WS_GUID).encode()).digest()).decode()
    if acept and acept != esperado:
        print("AVISO: Sec-WebSocket-Accept no coincide con el esperado (se continua)")
    sock.settimeout(timeout)
    return sock


def enviar_json(sock, obj):
    ws_escribir_frame(sock, 0x1, json.dumps(obj, ensure_ascii=False).encode("utf-8"))


def recibir_hasta(sock, audio, nombres):
    """Lee frames: binarios -> audio, ping -> pong, texto -> evento JSON.
    Devuelve (evento, header) cuando header.event esta en `nombres`, o ("close", {...})."""
    frag = None
    while True:
        fin, op, payload = ws_leer_frame(sock)
        if op == 0x8:
            code = struct.unpack("!H", payload[:2])[0] if len(payload) >= 2 else 1000
            razon = payload[2:].decode("utf-8", "replace") if len(payload) > 2 else ""
            return "close", {"code": code, "reason": razon}
        if op == 0x9:
            ws_escribir_frame(sock, 0xA, payload)
            continue
        if op == 0xA:
            continue
        if op == 0x2:
            audio.extend(payload)
            continue
        if op in (0x1, 0x0):
            if op == 0x1:
                frag = bytearray(payload)
            else:
                if frag is None:
                    frag = bytearray(payload)
                else:
                    frag.extend(payload)
            if not fin:
                continue
            data = bytes(frag)
            frag = None
            try:
                msg = json.loads(data.decode("utf-8", "replace"))
            except ValueError:
                continue
            header = msg.get("header") or {}
            ev = header.get("event") or ""
            if ev in nombres or ev == "task-failed":
                return ev, header


def hint_de_error_ws(exc_code, detalle):
    d = str(detalle).lower()
    if exc_code in (401, 403) or "invalidapikey" in d or "unauthorized" in d or "forbidden" in d:
        return ("key no valida para este host: sk-sp-* (Token Plan) => token-plan.maas.qwencloudapi.com; "
                "sk-*/sk-ws-* (pay-as-you-go) => maas.qwencloudapi.com")
    if "23 second" in d or "request timeout" in d:
        return "el servidor corto la conexion por inactividad: enviar el texto (continue-task) sin demora tras run-task"
    if "datainspectionfailed" in d or "data inspection" in d:
        return "texto bloqueado por moderacion: reescribir el guion"
    if "411" in d or "engine error" in d:
        return "voz no valida para el modelo: usar longanlingxin / longanlufeng o una base voice qwen-audio-3.0-tts-plus-* valida"
    if "1007" in d:
        return 'la conexion se cerro con 1007 (payload invalido): el run-task debe incluir "input": {}'
    if "model" in d and ("not exist" in d or "not available" in d or "unsupported" in d):
        return "modelo no disponible en tu plan; Token Plan: qwen-audio-3.0-tts-plus"
    return None


def normalizar_rest_url(url):
    """Acepta un base REST https://host/api/v1, o incluso una URL ws(s)/wss normalizable, y
    devuelve el base REST equivalente para el modo --http."""
    u = url.strip().rstrip("/")
    if u.startswith("wss://"):
        u = "https://" + u[len("wss://"):]
    elif u.startswith("ws://"):
        u = "http://" + u[len("ws://"):]
    u = u.replace("/api-ws/v1/inference", "/api/v1")
    return u


def tts_http_one_shot(base, key, payload, timeout):
    """POST documentado (doc TP best-practices/speech-synthesis): {base}/services/audio/tts/
    SpeechSynthesizer -> output.audio.url (validez 24 h). Un unico JSON de respuesta."""
    api = base.rstrip("/") + ENDPOINT_TTS_HTTP
    req = urllib.request.Request(api, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer " + key})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
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
        elif e.code in (401, 403) or code == "InvalidApiKey":
            hint = ("key invalida o key<->host incorrectos: sk-sp-* (Token Plan) => "
                    "token-plan.maas.qwencloudapi.com")
        elif code == "DataInspectionFailed":
            hint = "texto bloqueado por moderacion: reescribir el guion"
        elif "model" in str(msg).lower() or "not exist" in str(msg).lower():
            hint = "modelo no disponible en tu plan; Token Plan: qwen-audio-3.0-tts-plus"
        elif e.code == 400:
            hint = ("parametro invalido (voz/formato/sample_rate): la voz debe coincidir con la "
                    "version del modelo — usar longanlingxin/longanlufeng; ver seccion TTS HTTP de la reference")
        fallo(f"TTS HTTP {e.code} {code} {msg}", hint, 1)
    except Exception as e:
        fallo(f"conexion TTS HTTP: {e}", "revisar red/proxy; si falla, quitar --http (WS es la via verificada)", 1)


def main():
    ap = argparse.ArgumentParser(description="TTS via WebSocket con qwen-audio-3.0-tts-plus (QwenCloud)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--text", help="texto a sintetizar (cuidado con quoting en cmd)")
    g.add_argument("--text-file", help="archivo .txt con el texto (recomendado en Windows)")
    ap.add_argument("--voice", default="longanlingxin",
                    help="longanlingxin (F, default) | longanlufeng (M) | base voice qwen-audio-3.0-tts-plus-*")
    ap.add_argument("--format", choices=FORMATOS, default="mp3")
    ap.add_argument("--sample-rate", type=int, choices=SAMPLE_RATES, default=22050)
    ap.add_argument("--rate", type=float, default=1.0, help="velocidad 0.5-2.0")
    ap.add_argument("--pitch", type=float, default=1.0, help="tono 0.5-2.0")
    ap.add_argument("--volume", type=int, default=50, help="volumen 0-100")
    ap.add_argument("--seed", type=int, default=None, help="0-65535 (opcional)")
    ap.add_argument("--instruction", default=None, help="control en lenguaje natural, <=100 chars (opcional)")
    ap.add_argument("--output", required=True, help="ruta del archivo de audio de salida")
    ap.add_argument("--model", default=MODELO_DEFAULT)
    ap.add_argument("--base-url", default=None,
                    help="forzar endpoint (WS: wss://... o https://host/api/v1; con --http: base REST https://host/api/v1)")
    ap.add_argument("--http", action="store_true",
                    help="via HTTP one-shot (POST SpeechSynthesizer, doc TP 2026-11; descarga output.audio.url). "
                         "Default: WebSocket (via verificada empiricamente). Ignora rate/pitch/volume/seed/instruction")
    ap.add_argument("--timeout", type=int, default=120, help="inactividad maxima de lectura (s)")
    args = ap.parse_args()

    key = resolver_key()
    if not key:
        fallo("sin API key (DASHSCOPE_API_KEY / ANTHROPIC_AUTH_TOKEN / opencode auth.json)",
              "crearla en https://home.qwencloud.com/api-keys y exportarla (Windows: setx DASHSCOPE_API_KEY sk-xxx)", 2)

    texto = args.text
    if args.text_file:
        try:
            with open(args.text_file, encoding="utf-8") as f:
                texto = f.read().strip()
        except OSError as e:
            fallo(f"no puedo leer --text-file: {e}", None, 2)
    if not texto:
        fallo("falta --text o --text-file (texto vacio)", None, 2)
    if args.seed is not None and not 0 <= args.seed <= 65535:
        fallo("--seed fuera de rango (0-65535)", None, 2)
    if args.instruction is not None and len(args.instruction) > 100:
        fallo("--instruction maxima 100 caracteres", None, 2)
    if not 0.5 <= args.rate <= 2.0:
        fallo("--rate fuera de rango (0.5-2.0)", None, 2)
    if not 0.5 <= args.pitch <= 2.0:
        fallo("--pitch fuera de rango (0.5-2.0)", None, 2)
    if not 0 <= args.volume <= 100:
        fallo("--volume fuera de rango (0-100)", None, 2)
    if args.voice not in VOCES_SISTEMA and not args.voice.startswith(args.model + "-"):
        print(f"AVISO: voz '{args.voice}' no es de sistema ({' / '.join(VOCES_SISTEMA)}); "
              "asumo base voice de voice cloning. El audio puede salir en chino/ingles.", file=sys.stderr)

    # ---------- via HTTP one-shot (opcional; la via por defecto sigue siendo WS) ----------
    if args.http:
        ignorados = []
        if args.rate != 1.0:
            ignorados.append("--rate")
        if args.pitch != 1.0:
            ignorados.append("--pitch")
        if args.volume != 50:
            ignorados.append("--volume")
        if args.seed is not None:
            ignorados.append("--seed")
        if args.instruction is not None:
            ignorados.append("--instruction")
        if ignorados:
            print("AVISO: el modo --http solo envia los campos documentados (text/voice/format/"
                  f"sample_rate); se IGNORAN: {', '.join(ignorados)}. Para ellos usa la via WS (default).",
                  file=sys.stderr)
        if args.base_url:
            base_rest = normalizar_rest_url(args.base_url)
        elif key.startswith("sk-sp-"):
            base_rest = BASE_REST_TOKEN_PLAN
        else:
            base_rest = BASE_REST_PAYG
        payload_http = {"model": args.model, "input": {"text": texto, "voice": args.voice,
                        "format": args.format, "sample_rate": args.sample_rate}}
        t0h = time.time()
        data = tts_http_one_shot(base_rest, key, payload_http, args.timeout)
        out_http = data.get("output") or {}
        audio_http = (out_http.get("audio") or {}).get("url")
        if not audio_http:
            fallo("TTS HTTP: respuesta sin output.audio.url: "
                  + json.dumps(data, ensure_ascii=False)[:400],
                  "verificar voz/modelo (la voz debe coincidir con la version del modelo); "
                  "o quitar --http y usar la via WS verificada", 1)
        dh = os.path.dirname(os.path.abspath(args.output))
        if dh:
            os.makedirs(dh, exist_ok=True)
        try:
            with urllib.request.urlopen(audio_http, timeout=args.timeout) as r, open(args.output, "wb") as f:
                f.write(r.read())
        except Exception as e:
            fallo(f"descargando audio TTS HTTP: {e}", "la URL expira en 24 h; reintentar la sintesis", 1)
        print(json.dumps({
            "ok": True,
            "model": args.model,
            "voice": args.voice,
            "via": "http",
            "base": base_rest,
            "request_id": data.get("request_id"),
            "output": os.path.abspath(args.output),
            "bytes": os.path.getsize(args.output),
            "caracteres": len(texto),
            "characters_facturados": (data.get("usage") or {}).get("characters"),
            "url_expira": (out_http.get("audio") or {}).get("expires_at"),
            "segundos": round(time.time() - t0h, 1),
        }, ensure_ascii=False, indent=1))
        return

    # ---------- via WebSocket (default) ----------
    if args.base_url:
        candidatos = [normalizar_base_url(args.base_url)]
    elif key.startswith("sk-sp-"):
        candidatos = [WSS_TOKEN_PLAN, WSS_PAYG]  # fallback automatico (1 reintento)
    else:
        candidatos = [WSS_PAYG]

    sock = None
    usado = None
    for i, url in enumerate(candidatos):
        try:
            sock = ws_conectar(url, key, args.timeout)
            usado = url
            if i > 0:
                print(f"ADVERTENCIA: el host primario fallo; conexion establecida con el "
                      f"host alternativo {url}", file=sys.stderr)
            break
        except (HandshakeError, ConnectionError, OSError) as e:
            code = getattr(e, "http_code", 0)
            detalle = str(e)
            if i + 1 < len(candidatos):
                print(f"AVISO: handshake fallo en {url} ({detalle}); "
                      f"reintentando con {candidatos[i + 1]}", file=sys.stderr)
                continue
            fallo(f"handshake WS: {detalle}", hint_de_error_ws(code, detalle), 1)

    t0 = time.time()
    task_id = str(uuid.uuid4())
    audio = bytearray()
    try:
        # 1) run-task ("input": {} es OBLIGATORIO o el servidor cierra con 1007)
        parametros = {
            "text_type": "PlainText",
            "voice": args.voice,
            "format": args.format,
            "sample_rate": args.sample_rate,
            "volume": args.volume,
            "rate": args.rate,
            "pitch": args.pitch,
        }
        if args.seed is not None:
            parametros["seed"] = args.seed
        if args.instruction:
            parametros["instruction"] = args.instruction
        enviar_json(sock, {
            "header": {"action": "run-task", "task_id": task_id, "streaming": "duplex"},
            "payload": {
                "task_group": "audio", "task": "tts", "function": "SpeechSynthesizer",
                "model": args.model, "parameters": parametros, "input": {},
            },
        })

        # 2) esperar task-started
        ev, hdr = recibir_hasta(sock, audio, {"task-started"})
        if ev == "close":
            fallo(f"el servidor cerro la conexion antes de iniciar la tarea "
                  f"(code={hdr.get('code')} {hdr.get('reason')})",
                  hint_de_error_ws(0, str(hdr)), 1)
        if ev == "task-failed":
            fallo(f"task-failed en run-task: {hdr.get('error_code')} {hdr.get('error_message')}",
                  hint_de_error_ws(0, str(hdr.get("error_message") or "")), 1)

        # 3) continue-task con el texto (troceado <=15000 chars, enviado SIN demora)
        for j in range(0, len(texto), CHUNK_MAX):
            enviar_json(sock, {
                "header": {"action": "continue-task", "task_id": task_id, "streaming": "duplex"},
                "payload": {"input": {"text": texto[j:j + CHUNK_MAX]}},
            })

        # 4) finish-task (SIEMPRE, o se pierde el final del audio)
        enviar_json(sock, {
            "header": {"action": "finish-task", "task_id": task_id, "streaming": "duplex"},
            "payload": {"input": {}},
        })

        # 5) recibir result-generated + frames binarios hasta task-finished
        while True:
            ev, hdr = recibir_hasta(sock, audio, {"task-finished"})
            if ev == "task-finished":
                break
            if ev == "task-failed":
                fallo(f"task-failed: {hdr.get('error_code')} {hdr.get('error_message')}",
                      hint_de_error_ws(0, str(hdr.get("error_message") or "")), 1)
            if ev == "close":
                if audio:
                    print(f"AVISO: conexion cerrada por el servidor sin task-finished "
                          f"(code={hdr.get('code')} {hdr.get('reason')}); audio posible truncado",
                          file=sys.stderr)
                    break
                fallo(f"el servidor cerro la conexion sin enviar audio "
                      f"(code={hdr.get('code')} {hdr.get('reason')})",
                      hint_de_error_ws(0, str(hdr)), 1)
    except socket.timeout:
        fallo(f"sin datos del servidor durante {args.timeout} s (inactividad WS)",
              "aumentar --timeout o verificar red; el servidor corta tras 23 s sin recibir texto", 1)
    except ConnectionError as e:
        if audio:
            print(f"AVISO: {e}; se conservan {len(audio)} bytes ya recibidos", file=sys.stderr)
        else:
            fallo(f"conexion WS: {e}", None, 1)
    finally:
        try:
            ws_escribir_frame(sock, 0x8, struct.pack("!H", 1000))
            sock.close()
        except OSError:
            pass

    if not audio:
        fallo("la tarea termino sin frames de audio", "revisar formato/texto; reintentar", 1)

    d = os.path.dirname(os.path.abspath(args.output))
    if d:
        os.makedirs(d, exist_ok=True)
    try:
        with open(args.output, "wb") as f:
            f.write(bytes(audio))
    except OSError as e:
        fallo(f"escribiendo --output: {e}", None, 1)

    print(json.dumps({
        "ok": True,
        "model": args.model,
        "voice": args.voice,
        "base": usado,
        "output": os.path.abspath(args.output),
        "bytes": len(audio),
        "caracteres": len(texto),
        "segundos": round(time.time() - t0, 1),
    }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
