# Ambilight — LG OLED65C2 + WLED

Sistema de retroiluminación reactiva para una LG OLED65C2 rooteada, con panel
de control propio, auto-reparación e integración con Home Assistant.

```
TV (plano de video)
  └─ PicCap ───── libvtcapture ─ captura
       └─ flatbuffer :19400 ──→ HyperHDR ── mapea 180 zonas
                                   └─ UDP ──→ WLED ──→ tira SK6812 RGBW
                                                 ▲
  Panel de control (LXC 110) ────────────────────┘
       └─ Home Assistant (sensores, switches, acciones)
```

Los cuatro eslabones corren en equipos distintos. **Esa es la causa de casi
todos los problemas**, y por qué el panel existe: dice *cuál* se rompió.

---

> **Las direcciones de este repositorio son ejemplos.** Ajústalas a tu red:
> `192.168.1.10` = TV · `192.168.1.11` = controlador · `192.168.1.20` = panel ·
> `192.168.1.2` = Proxmox · `192.168.1.30` = Home Assistant.
> `server.py` lee `AMBI_TV`, `AMBI_WLED`, `AMBI_PORT`, `AMBI_BIND` y
> `AMBI_SSH_KEY` del entorno, así que no hace falta editarlo.

## Acceso rápido

| Qué | Dónde |
|---|---|
| Panel de control | <http://192.168.1.20:8777> |
| Pruebas de posición | <http://192.168.1.20:8777/pruebas> |
| WLED | <http://wled-xxxxxx.local> |
| HyperHDR (API) | `http://192.168.1.10:8090/json-rpc` |

```sh
# salud de toda la cadena en una línea
curl -s http://192.168.1.20:8777/api/estado | python -c "import sys,json;d=json.load(sys.stdin);print(d['cadena'])"
```

---

## Hardware

| Pieza | Modelo | Notas |
|---|---|---|
| TV | LG OLED65C2PSA, webOS 11.2.0 | rooteada, Homebrew Channel 0.7.3 |
| Controlador | GLEDOPTO Elite **2D-EXMU** (`GL-C-I-616WL`) | ESP32 + WLED 0.15.4 |
| Tira | SK6812 **RGBNW**, 3 m, 60 LED/m, IP30 | **180 LEDs**, 5 V |
| Fuente | `JC0515`, 5 V / 15 A (75 W) | centro positivo |

La serigrafía del controlador se lee "ZD-EXMU" pero el carácter es un **2**.

Detalles de cableado, pinout y montaje: **[docs/hardware.md](docs/hardware.md)**.

---

## Software

### En la TV

| Componente | Rol | Crítico |
|---|---|---|
| **PicCap** 0.5.3 | Captura el plano de video vía `libvtcapture` | Debe correr **como root** |
| **HyperHDR** 22.0.0 | Mapea la imagen a 180 LEDs y transmite | Config en SQLite |

PicCap **no es un ambilight**: es el emisor de captura. HyperHDR en webOS no
captura nada por sí solo — su binario solo trae grabbers de `framebuffer`,
`pipewire` y `amlogic`, ninguno sirve para el plano de video de una LG.

### En el Proxmox (LXC 110, `192.168.1.20`)

| Archivo | Qué es |
|---|---|
| `server.py` | Servidor y proxy. Sin dependencias externas salvo `websocket-client` |
| `index.html` | Panel de control |
| `pruebas.html` | Patrones de prueba a pantalla completa |
| `presets.json` | Presets, editables |
| `deploy.sh` | Crea el LXC e instala el servicio systemd |

**Por qué hay un servidor y no basta un HTML:** HyperHDR habla HTTP sin CORS.
Una página servida desde otro origen no puede llamarlo, y una publicada por
HTTPS menos (contenido mixto). El proxy resuelve ambos, y habilita el guardado
en disco, que necesita SSH.

---

## Instalación desde cero

```sh
scp server.py index.html pruebas.html presets.json deploy.sh root@PROXMOX:/root/
ssh root@PROXMOX "bash /root/deploy.sh --crear 110"
```

El script crea un LXC Debian sin privilegios, instala dependencias, genera una
llave SSH propia para la TV, e instala el servicio con `enable --now`.
**Al final imprime una llave pública que hay que autorizar en la TV**, o el
panel solo podrá leer estado.

El LXC necesita además `avahi-daemon` y `libnss-mdns` para resolver `.local`.

---

## Configuración actual

### WLED
| Campo | Valor | Por qué |
|---|---|---|
| LED type | `SK6812 RGBW` | Con `WS281x` manda 24 bits/LED y la tira espera 32 |
| Color Order | `GRB` | |
| GPIO | `16` | salida 1 del controlador |
| Length | `180` | |
| mA/LED | `80` | son 4 chips, no 3 |
| Max Current | `12000` | margen sobre la fuente de 15 A |
| RGBW Mode | `Accurate` | usa el canal W solo en blancos y grises |

### HyperHDR
| Campo | Valor |
|---|---|
| Device | `wled` → **`wled-xxxxxx.local`**, 180 LEDs, `colorOrder: rgb` |
| Layout | 48 izquierda (subiendo) · 84 arriba · 48 derecha (bajando) |
| Suavizado | **apagado** (mínima latencia) |
| `luminanceGain` | `0.5` |
| `backlightThreshold` | `0` (se apagan en negro) |

### PicCap
`address: 127.0.0.1`, `port: 19400`, **`fps: 40`**, `vsync: false`,
`autostart: true`.

> **`fps` nunca debe pasar de 40.** El hardware entrega un frame cada 25 ms;
> pedir 60 quema CPU sin ganar nada y produce lag visible.

---

## Funciones del panel

**Estado** — fps de captura y de la tira, consumo, LEDs, señal WiFi, y una
línea que dice si la cadena está activa y, si no, *cuál* eslabón falló.

**Presets** — Película · Juego · Normal · Noche. Toque aplica; pulsación larga
sobrescribe con los valores actuales.

**Imagen** — brillo, piso de luz, suavizado. Aplican en vivo.

**Vigilante** — detecta la cadena rota y reinicia PicCap solo. Ver
[docs/operacion.md](docs/operacion.md).

**Vista previa** — los 180 LEDs en vivo, dibujados en la posición que HyperHDR
dice que muestrean. El layout se lee de su API, no está hardcodeado.

**Pruebas de posición** — página a pantalla completa para mostrar en la TV.
Pinta patrones en las orillas para verificar qué LED físico corresponde a cada
zona.

---

## API

| Método | Ruta | Qué hace |
|---|---|---|
| GET | `/api/estado` | Estado completo + `cadena`, `preset`, `vigilante` |
| GET | `/api/eventos` | Bitácora del vigilante |
| GET | `/api/presets` | Lista de presets |
| GET | `/api/leds` | Colores en vivo + layout |
| POST | `/api/ajuste` | `{luminanceGain, backlightThreshold, ...}` |
| POST | `/api/componente` | `{nombre: "SMOOTHING", estado: bool}` |
| POST | `/api/wled` | Estado de WLED (`on`, `bri`, …) |
| POST | `/api/preset` | `{nombre}` |
| POST | `/api/preset-guardar` | `{nombre}` — sobrescribe con lo actual |
| POST | `/api/vigilante` | `{activo: bool}` |
| POST | `/api/piccap-reiniciar` | |
| POST | `/api/guardar` | Persiste en la TV (~35 s) |

Los cambios por `/api/ajuste` y `/api/componente` **aplican en vivo pero no
persisten**. `/api/guardar` los escribe en disco.

---

## Integración

**Home Assistant** — 6 sensores, 3 interruptores y 4 acciones.
Ver [docs/home-assistant.md](docs/home-assistant.md).

**Homepage** — entrada en el grupo Infraestructura con widget `customapi`
contra `/api/estado`. Script idempotente en `homepage-add.py`.

---

## Limitación conocida: DRM

**Netflix, Apple TV y Disney+ no llegan a la tira.** Medido: con Netflix en
primer plano, los 180 LEDs leen `(0,0,0)` exacto, sin variación entre ellos.
Una escena oscura real daría valores bajos pero distintos.

webOS decodifica el contenido protegido en memoria segura que la CPU no puede
leer, así que `vtcapture` recibe un plano vacío. **Ninguna app del catálogo de
Homebrew lo arregla** — el bloqueo está debajo de la capa de apps.

Opciones evaluadas en [docs/operacion.md](docs/operacion.md#drm).

---

## Documentación

- **[docs/hardware.md](docs/hardware.md)** — tira, controlador, cableado, layout
- **[docs/operacion.md](docs/operacion.md)** — diagnóstico, trampas, DRM
- **[docs/home-assistant.md](docs/home-assistant.md)** — entidades y YAML
