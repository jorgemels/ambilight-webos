#!/usr/bin/env python3
"""Panel de control local del ambilight (HyperHDR + PicCap + WLED).

Sirve la pagina en http://localhost:8777 y hace de proxy hacia la TV y el
controlador. El proxy existe porque el navegador no puede llamar directo a
endpoints HTTP de la red local desde una pagina servida por otro origen.
"""
import json
import os
import re
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Configurable por entorno para poder correrlo igual en el PC que en el servidor.
TV = os.environ.get("AMBI_TV", "192.168.1.10")        # HyperHDR escucha en :8090
WLED = os.environ.get("AMBI_WLED", "wled-xxxxxx.local")  # por nombre: la IP cambia
PORT = int(os.environ.get("AMBI_PORT", "8777"))
# En el PC basta localhost; en el servidor hay que escuchar en la red.
BIND = os.environ.get("AMBI_BIND", "127.0.0.1")
SSH_KEY = os.environ.get("AMBI_SSH_KEY", "")            # llave para hablarle a la TV
HERE = Path(__file__).resolve().parent

HYPERHDR_SVC = "org.webosbrew.hyperhdr.loader.service"
PICCAP_SVC = "org.webosbrew.piccap.service"


def http_json(url, payload=None, timeout=8):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode(errors="replace")
    return json.loads(body) if body.strip() else {}


def hyperhdr(payload):
    return http_json("http://" + TV + ":8090/json-rpc", payload)


# Resolver el nombre mDNS cuesta ~3 s cada vez, asi que se guarda la IP. Si una
# peticion falla se descarta y se vuelve a resolver: eso es lo que permite usar
# el nombre (inmune a que el DHCP mueva la IP) sin pagar el costo en cada lectura.
_wled_ip = None


def wled_json(path, payload=None):
    global _wled_ip
    for intento in (1, 2):
        try:
            if _wled_ip is None:
                _wled_ip = socket.gethostbyname(WLED)
            return http_json("http://" + _wled_ip + path, payload)
        except Exception:
            _wled_ip = None
            if intento == 2:
                raise
    raise RuntimeError("inalcanzable")


def _ssh_base(tty=False):
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
           "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR"]
    if tty:
        cmd.append("-tt")
    if SSH_KEY:
        cmd += ["-i", SSH_KEY]
    return cmd + ["root@" + TV]


def ssh_python(script, timeout=90):
    """Corre python3 en la TV."""
    proc = subprocess.run(_ssh_base() + ["python3 -"], input=script,
                          capture_output=True, text=True, timeout=timeout)
    return {"rc": proc.returncode, "out": proc.stdout.strip(),
            "err": proc.stderr.strip()}


def luna(service, method, timeout=25):
    """luna-send necesita TTY, por eso el -tt."""
    cmd = "luna-send -n 1 -w 10000 luna://{}/{} '{{}}'".format(service, method)
    try:
        proc = subprocess.run(_ssh_base(tty=True) + [cmd],
                              capture_output=True, text=True, timeout=timeout)
        return proc.stdout
    except subprocess.TimeoutExpired:
        return ""


# Los cambios por API aplican en vivo pero NO sobreviven un reinicio.
# Persistir exige parar hyperhdr, escribir sqlite, arrancarlo y reiniciar PicCap.
PERSIST_SCRIPT = """
import sqlite3, json, sys
vals = json.loads(sys.stdin.read())
c = sqlite3.connect("/home/root/.config/HyperHDR/db/hyperhdr.db")
stamp = "strftime('%Y-%m-%dT%H:%M:%SZ','now')"

col = json.loads(list(c.execute(
    "select config from settings where type='color'"))[0][0])
for a in col["channelAdjustment"]:
    for k in ("luminanceGain", "backlightThreshold", "backlightColored"):
        if k in vals:
            a[k] = vals[k]
c.execute("update settings set config=?, updated_at=" + stamp +
          " where type='color'", (json.dumps(col),))

if "smoothingEnable" in vals or "smoothingTime" in vals:
    sm = json.loads(list(c.execute(
        "select config from settings where type='smoothing'"))[0][0])
    if "smoothingEnable" in vals:
        sm["enable"] = vals["smoothingEnable"]
    if "smoothingTime" in vals:
        sm["time_ms"] = vals["smoothingTime"]
    c.execute("update settings set config=?, updated_at=" + stamp +
              " where type='smoothing'", (json.dumps(sm),))
c.commit()
print("ok")
"""


# El estado de PicCap solo se consigue por ssh y tarda ~3 s. Pedirlo en cada
# refresco encimaria las peticiones, asi que un hilo lo renueva aparte y las
# respuestas leen la ultima foto.
_piccap = {"ok": False, "error": "arrancando", "edad": None}
_piccap_lock = threading.Lock()
PICCAP_CADA = 15


def _lee_piccap():
    try:
        texto = luna(PICCAP_SVC, "status")
        match = re.search(r"\{.*\}", texto, re.S)
        if not match:
            return {"ok": False, "error": "la TV no respondio"}
        data = json.loads(match.group(0))
        return {"ok": True, "fps": round(data.get("framerate", 0), 1),
                "conectado": data.get("connected"),
                "elevado": data.get("elevated"),
                "corriendo": data.get("isRunning")}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _refresca_piccap():
    global _piccap
    while True:
        nuevo = _lee_piccap()
        nuevo["visto"] = time.time()
        with _piccap_lock:
            _piccap = nuevo
        time.sleep(PICCAP_CADA)


def piccap_estado():
    with _piccap_lock:
        d = dict(_piccap)
    visto = d.pop("visto", None)
    d["edad"] = round(time.time() - visto) if visto else None
    return d


def invalida_piccap():
    """Tras reiniciar PicCap no esperamos al ciclo: releemos ya."""
    nuevo = _lee_piccap()
    nuevo["visto"] = time.time()
    global _piccap
    with _piccap_lock:
        _piccap = nuevo


# ------------------------------------------------------- vista previa LEDs
# HyperHDR solo entrega los colores en vivo por WebSocket. Para no cargar a la
# TV con un stream que casi nadie mira, se conecta SOLO mientras alguien pide
# /api/leds y se desconecta unos segundos despues.
try:
    import websocket as _ws
except ImportError:
    _ws = None

LEDS_GRACIA = 10          # segundos sin peticiones antes de cortar el stream
_leds = {"datos": None, "visto": 0}
_leds_demanda = 0.0
_leds_lock = threading.Lock()
_layout = {"datos": None, "visto": 0}


def layout_leds():
    """Posiciones de cada LED segun HyperHDR, no hardcodeadas."""
    with _leds_lock:
        if _layout["datos"] and time.time() - _layout["visto"] < 300:
            return _layout["datos"]
    try:
        datos = hyperhdr({"command": "serverinfo"})["info"]["leds"]
    except Exception:
        return None
    with _leds_lock:
        _layout.update(datos=datos, visto=time.time())
    return datos


def _stream_leds():
    while True:
        if _ws is None or time.time() - _leds_demanda > LEDS_GRACIA:
            time.sleep(1)
            continue
        ws = None
        try:
            ws = _ws.create_connection("ws://%s:8090/" % TV, timeout=6)
            ws.send(json.dumps({"command": "ledcolors",
                                "subcommand": "ledstream-start", "tan": 1}))
            registra("Vista previa de LEDs conectada", "info")
            while time.time() - _leds_demanda <= LEDS_GRACIA:
                msg = json.loads(ws.recv())
                if msg.get("command") != "ledcolors-ledstream-update":
                    continue
                v = (msg.get("result") or {}).get("leds") or []
                with _leds_lock:
                    _leds["datos"] = [v[i:i + 3] for i in range(0, len(v), 3)]
                    _leds["visto"] = time.time()
            ws.send(json.dumps({"command": "ledcolors",
                                "subcommand": "ledstream-stop", "tan": 2}))
        except Exception:
            time.sleep(2)
        finally:
            try:
                if ws:
                    ws.close()
            except Exception:
                pass
            with _leds_lock:
                _leds["datos"] = None


def leds_vista():
    global _leds_demanda
    _leds_demanda = time.time()
    with _leds_lock:
        datos, visto = _leds["datos"], _leds["visto"]
    out = {"leds": datos, "layout": layout_leds()}
    if _ws is None:
        out["error"] = "falta la libreria websocket en el servidor"
    elif datos is None:
        out["conectando"] = True
    else:
        out["edad"] = round(time.time() - visto, 2)
    return out


# ---------------------------------------------------------------- presets
# Viven en disco, no en la pagina, para poder editarlos y para que sobrevivan
# un redespliegue. Un preset solo toca lo que NO requiere reiniciar HyperHDR,
# asi se aplica al instante.
PRESETS_FILE = HERE / "presets.json"
PRESETS_BASE = [
    {"nombre": "Película", "icono": "🎬", "luminanceGain": 0.35,
     "backlightThreshold": 0.0, "suavizado": False},
    {"nombre": "Juego", "icono": "🎮", "luminanceGain": 0.6,
     "backlightThreshold": 0.0, "suavizado": False},
    {"nombre": "Normal", "icono": "📺", "luminanceGain": 0.5,
     "backlightThreshold": 0.0039, "suavizado": False},
    {"nombre": "Noche", "icono": "🌙", "luminanceGain": 0.15,
     "backlightThreshold": 0.0039, "suavizado": True},
]


def lee_presets():
    try:
        return json.loads(PRESETS_FILE.read_text(encoding="utf-8"))
    except Exception:
        escribe_presets(PRESETS_BASE)
        return list(PRESETS_BASE)


def escribe_presets(lista):
    PRESETS_FILE.write_text(json.dumps(lista, ensure_ascii=False, indent=2),
                            encoding="utf-8")


def busca_preset(nombre):
    for p in lee_presets():
        if p["nombre"].lower() == str(nombre).lower():
            return p
    return None


def aplica_preset(nombre):
    p = busca_preset(nombre)
    if not p:
        raise ValueError("no existe el preset %r" % nombre)
    hyperhdr({"command": "adjustment", "adjustment": {
        "luminanceGain": p["luminanceGain"],
        "backlightThreshold": p["backlightThreshold"],
        "backlightColored": p["backlightThreshold"] > 0}})
    hyperhdr({"command": "componentstate", "componentstate": {
        "component": "SMOOTHING", "state": bool(p["suavizado"])}})
    registra("Preset aplicado: %s" % p["nombre"], "info")
    return p


def guarda_preset_actual(nombre):
    """Sobrescribe un preset con lo que esta puesto ahora mismo."""
    est = lee_estado()
    h = est["hyperhdr"]
    if not h.get("ok"):
        raise RuntimeError("HyperHDR no responde")
    lista = lee_presets()
    for p in lista:
        if p["nombre"].lower() == str(nombre).lower():
            p["luminanceGain"] = h.get("luminanceGain")
            p["backlightThreshold"] = h.get("backlightThreshold")
            p["suavizado"] = bool(h.get("suavizado"))
            escribe_presets(lista)
            registra("Preset «%s» actualizado con los valores actuales"
                     % p["nombre"], "ok")
            return p
    raise ValueError("no existe el preset %r" % nombre)


def reinicia_piccap():
    luna(PICCAP_SVC, "stop")
    time.sleep(3)
    luna(PICCAP_SVC, "start", timeout=40)
    time.sleep(4)
    invalida_piccap()
    return piccap_estado()


def lee_estado():
    out = {"tv": TV, "wled_host": WLED}
    try:
        info = hyperhdr({"command": "serverinfo"})["info"]
        comps = {c["name"]: c["enabled"] for c in info.get("components", [])}
        activas = [p for p in info.get("priorities", []) if p.get("active")]
        adj = (info.get("adjustment") or [{}])[0]
        out["hyperhdr"] = {
            "ok": True,
            "fuente": activas[0]["componentId"] if activas else None,
            "suavizado": comps.get("SMOOTHING"),
            "leddevice": comps.get("LEDDEVICE"),
            "luminanceGain": adj.get("luminanceGain"),
            "backlightThreshold": adj.get("backlightThreshold"),
        }
    except Exception as exc:
        out["hyperhdr"] = {"ok": False, "error": str(exc)}
    try:
        data = wled_json("/json")
        info, state = data["info"], data["state"]
        out["wled"] = {"ok": True, "live": info["live"],
                       "fps": info["leds"]["fps"], "pwr": info["leds"]["pwr"],
                       "count": info["leds"]["count"],
                       "rssi": info["wifi"]["rssi"],
                       "bri": state["bri"], "on": state["on"],
                       "ip": info.get("ip")}
    except Exception as exc:
        out["wled"] = {"ok": False, "error": str(exc)}
    out["piccap"] = piccap_estado()
    h, w, p = out["hyperhdr"], out["wled"], out["piccap"]
    out["cadena"] = ("activa" if (h.get("ok") and h.get("fuente")
                                  and h.get("leddevice") and w.get("ok")
                                  and w.get("live") and p.get("conectado"))
                     else "rota")
    out["vigilante"] = vigilante_estado()
    h = out["hyperhdr"]
    out["preset"] = None
    if h.get("ok"):
        for p in lee_presets():
            if (abs((h.get("luminanceGain") or 0) - p["luminanceGain"]) < 0.001
                    and abs((h.get("backlightThreshold") or 0)
                            - p["backlightThreshold"]) < 0.0001
                    and bool(h.get("suavizado")) == bool(p["suavizado"])):
                out["preset"] = p["nombre"]
                break
    return out


# ------------------------------------------------------------- vigilante
# PicCap abre la conexion hacia HyperHDR y NO la reabre solo: si HyperHDR se
# reinicia quedan ambos vivos pero sin hablarse, y nada lo delata salvo que la
# tira deje de responder. Esto lo detecta y lo repara.
VIG_CADA = 20              # cada cuanto evalua
VIG_FALLAS = 3             # ~60 s roto antes de actuar, para no reaccionar a un parpadeo
VIG_ESPERA = 300           # 5 min entre reparaciones
VIG_MAX = 3                # tras 3 intentos fallidos se rinde y avisa

_eventos = []
_eventos_lock = threading.Lock()
_vig = {"activo": True, "fallas": 0, "intentos": 0,
        "ultimo_arreglo": 0, "rendido": False}
_vig_lock = threading.Lock()


def registra(texto, tipo="info"):
    with _eventos_lock:
        _eventos.append({"t": time.time(), "tipo": tipo, "texto": texto})
        del _eventos[:-60]


def eventos():
    with _eventos_lock:
        return list(reversed(_eventos))


def vigilante_estado():
    with _vig_lock:
        v = dict(_vig)
    v["desde_ultimo_arreglo"] = (round(time.time() - v["ultimo_arreglo"])
                                 if v["ultimo_arreglo"] else None)
    return v


def _diagnostica(est):
    """Devuelve el motivo si esto es reparable reiniciando PicCap, o None.

    Si la TV no responde damos por hecho que esta apagada: no es una falla y
    reiniciar no serviria de nada."""
    if not est["hyperhdr"].get("ok"):
        return None
    p, w = est["piccap"], est["wled"]
    if not p.get("ok"):
        return None                      # la TV no contesta por ssh
    if not p.get("conectado"):
        return "PicCap perdio la conexion con HyperHDR"
    if not est["hyperhdr"].get("fuente"):
        return "HyperHDR dejo de recibir video"
    if w.get("ok") and w.get("live") and w.get("fps") == 0:
        return "el controlador recibe 0 fps"
    return None


def _vigilante():
    time.sleep(30)                        # deja que todo levante
    while True:
        time.sleep(VIG_CADA)
        with _vig_lock:
            if not _vig["activo"]:
                _vig["fallas"] = 0
                continue
        try:
            est = lee_estado()
        except Exception:
            continue
        motivo = _diagnostica(est)

        with _vig_lock:
            if motivo is None:
                if _vig["fallas"] or _vig["rendido"]:
                    registra("Cadena sana de nuevo", "ok")
                _vig.update(fallas=0, intentos=0, rendido=False)
                continue
            _vig["fallas"] += 1
            fallas, intentos, rendido = (_vig["fallas"], _vig["intentos"],
                                         _vig["rendido"])
            desde = time.time() - _vig["ultimo_arreglo"]

        if fallas < VIG_FALLAS or rendido:
            continue
        if desde < VIG_ESPERA:
            continue
        if intentos >= VIG_MAX:
            with _vig_lock:
                _vig["rendido"] = True
            registra("Me rindo tras %d intentos: %s. Requiere revision manual."
                     % (VIG_MAX, motivo), "error")
            continue

        registra("Detectado: %s. Reiniciando PicCap." % motivo, "aviso")
        with _vig_lock:
            _vig["intentos"] += 1
            _vig["ultimo_arreglo"] = time.time()
            _vig["fallas"] = 0
        try:
            p = reinicia_piccap()
            if p.get("conectado"):
                registra("Reparado: PicCap reconectado a %.1f fps"
                         % (p.get("fps") or 0), "ok")
                with _vig_lock:
                    _vig["intentos"] = 0
            else:
                registra("El reinicio no reconecto PicCap", "error")
        except Exception as exc:
            registra("Fallo al reiniciar PicCap: %s" % exc, "error")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code, body, ctype="application/json"):
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            page = HERE / "index.html"
            return self._send(200, page.read_bytes(), "text/html; charset=utf-8")
        if self.path in ("/pruebas", "/pruebas.html"):
            page = HERE / "pruebas.html"
            return self._send(200, page.read_bytes(), "text/html; charset=utf-8")
        if self.path == "/api/estado":
            return self._send(200, self._estado())
        if self.path == "/api/eventos":
            return self._send(200, {"eventos": eventos()})
        if self.path == "/api/presets":
            return self._send(200, {"presets": lee_presets()})
        if self.path == "/api/leds":
            return self._send(200, leds_vista())
        self._send(404, {"error": "no existe"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        try:
            if self.path == "/api/ajuste":
                return self._send(200, hyperhdr(
                    {"command": "adjustment", "adjustment": body}))
            if self.path == "/api/componente":
                return self._send(200, hyperhdr({
                    "command": "componentstate",
                    "componentstate": {"component": body["nombre"],
                                       "state": bool(body["estado"])}}))
            if self.path == "/api/wled":
                return self._send(200, wled_json("/json/state", body))
            if self.path == "/api/piccap-reiniciar":
                registra("Reinicio manual de PicCap", "info")
                return self._send(200, {"ok": True, "piccap": reinicia_piccap()})
            if self.path == "/api/preset":
                return self._send(200, aplica_preset(body["nombre"]))
            if self.path == "/api/preset-guardar":
                return self._send(200, guarda_preset_actual(body["nombre"]))
            if self.path == "/api/vigilante":
                with _vig_lock:
                    _vig["activo"] = bool(body.get("activo"))
                    _vig.update(fallas=0, intentos=0, rendido=False)
                registra("Vigilante %s" % ("activado" if body.get("activo")
                                           else "desactivado"), "info")
                return self._send(200, vigilante_estado())
            if self.path == "/api/guardar":
                return self._send(200, self._guardar(body))
        except urllib.error.URLError as exc:
            return self._send(502, {"error": "sin respuesta: %s" % exc.reason})
        except Exception as exc:
            return self._send(500, {"error": str(exc)})
        self._send(404, {"error": "no existe"})

    def _estado(self):
        return lee_estado()

    def _guardar(self, vals):
        luna(HYPERHDR_SVC, "stop")
        time.sleep(4)
        res = ssh_python(PERSIST_SCRIPT.replace(
            "sys.stdin.read()", repr(json.dumps(vals))))
        luna(HYPERHDR_SVC, "start", timeout=40)
        time.sleep(14)
        reinicia_piccap()
        registra("Ajustes guardados en disco", "ok")
        return {"ok": res["rc"] == 0 and res["out"].endswith("ok"),
                "detalle": res}


if __name__ == "__main__":
    threading.Thread(target=_refresca_piccap, daemon=True).start()
    threading.Thread(target=_vigilante, daemon=True).start()
    threading.Thread(target=_stream_leds, daemon=True).start()
    registra("Panel iniciado", "info")
    servidor = ThreadingHTTPServer((BIND, PORT), Handler)
    print("Panel de ambilight  ->  http://%s:%d" %
          ("localhost" if BIND == "127.0.0.1" else BIND, PORT))
    print("  TV   %s" % TV)
    print("  WLED %s" % WLED)
    print("Ctrl-C para salir.")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nadios")
