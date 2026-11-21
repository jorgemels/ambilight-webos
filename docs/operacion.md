# Operación y diagnóstico

## Lo primero que hay que saber

**La cadena se rompe de una forma silenciosa y engañosa.**

PicCap abre la conexión hacia HyperHDR y **no la reabre solo**. Si HyperHDR se
reinicia, quedan ambos procesos vivos pero sin hablarse:

| Señal | Cuando está sano | Cuando está roto así |
|---|---|---|
| Procesos | corriendo | **corriendo igual** |
| `piccap status.connected` | `true` | **`true` también** ⚠️ |
| WLED `live` | `true` | **`true` también** ⚠️ |
| WLED `fps` | 50–90 | **`0`** |
| HyperHDR `priorities` | `FLATBUFSERVER active` | ausente |
| HyperHDR `LEDDEVICE` | `true` | `false` |

> **PicCap miente**: sigue reportando `connected: true` aunque no mande nada.
> Por eso el vigilante cruza los tres componentes en vez de fiarse de él.

**Regla: reiniciar HyperHDR ⇒ reiniciar PicCap.**

```sh
ssh root@192.168.1.10 "luna-send -n 1 -w 6000 luna://org.webosbrew.piccap.service/stop '{}'; sleep 3; luna-send -n 1 -w 10000 luna://org.webosbrew.piccap.service/start '{}'"
```

## El vigilante

Hilo en `server.py` que detecta y repara esto solo.

| Parámetro | Valor | Por qué |
|---|---|---|
| Revisión | 20 s | |
| Confirmaciones antes de actuar | 3 (~60 s) | no reaccionar a un parpadeo |
| Espera entre reparaciones | 5 min | evitar ciclos de reinicio |
| Máximo de intentos | 3 | rendirse y avisar en vez de insistir |

Detecta tres síntomas: PicCap sin conexión · HyperHDR sin fuente · WLED a 0 fps.

**Si la TV no responde no hace nada.** Una TV apagada no es una falla, y
reiniciar PicCap no serviría — solo ensuciaría la bitácora cada noche.

Probado dos veces rompiendo la cadena a propósito: reparó en 7 s y en 8 s,
detectando síntomas **distintos** cada vez.

## Diagnóstico por síntoma

| Lo que ves | Causa | Arreglo |
|---|---|---|
| Tira apagada o congelada | PicCap desconectado | `/api/piccap-reiniciar` |
| Pide rojo y sale **verde** | Color Order | `GRB` ↔ `RGB` en WLED |
| Los primeros LEDs bien, luego se **corren** | LED type | `SK6812 RGBW`, no `WS281x` |
| Solo enciende una **porción** | Length mal, o LED type en RGB | ver abajo |
| Colores **espejeados** | Tira montada al revés | revisar flechas del PCB |
| Netflix da **negro total** | DRM | ver [DRM](#drm) |
| **Lag** general de la TV | `fps` de PicCap por encima de 40 | bajarlo a 40 |

### Aritmética útil

Si WLED está en RGB (3 bytes/LED) y la tira es RGBW (4 bytes/LED), encienden
**¾ de los configurados**. Con 30 configurados: 30 × 3 ÷ 4 = **22.5**, o sea
22 encendidos y el 23 a medias. Ver 22 cuando esperas 30 **es ese problema**.

> No contar LEDs con un efecto corriendo: hay LEDs en negro y el conteo sale
> bajo. Siempre con color sólido.

## Comandos

```sh
# salud completa
curl -s http://192.168.1.20:8777/api/estado | python -m json.tool

# ¿dónde está el controlador? (la IP cambia; el nombre no)
ping wled-xxxxxx.local

# estado de PicCap  (luna-send NECESITA tty: ssh -tt)
ssh -tt root@192.168.1.10 "luna-send -n 1 -w 6000 luna://org.webosbrew.piccap.service/status '{}'"

# ¿está capturando el hardware?  (debe mostrar diff[25msec])
ssh root@192.168.1.10 "dmesg | grep vt_capture_thread | tail -5"

# prueba end-to-end: fuerza un color
ssh root@192.168.1.10 "curl -s -X POST http://127.0.0.1:8090/json-rpc -H 'Content-Type: application/json' -d '{\"command\":\"color\",\"color\":[0,0,255],\"priority\":50}'"

# servicio del panel
ssh root@192.168.1.2 "pct exec 110 -- journalctl -u ambilight -n 50 --no-pager"
```

## Trampas que ya costaron tiempo

**`pkill -f hyperhdr` mata su propio shell SSH**, porque el patrón aparece en
su línea de comando. Hay que poner el corchete en **todas** las apariciones del
literal dentro del mismo comando, incluido cualquier `case` o `grep` posterior:
`pkill -f 'hyperhd[r]/hyperhd[r]'`. Más seguro: hacer el stop en una llamada
SSH aparte. (`pgrep -c -f` con ese patrón reporta 0 aunque el proceso viva —
leer `/proc/<pid>/cmdline`.)

**`ps` trunca los nombres a 15 caracteres** y algunos daemons aparecen solo
como `python3`. Leer `/proc/<pid>/cmdline`.

**`fps: 0` en PicCap NO significa "sin límite"** — es literal, la captura cae
a ~30 fps. Hay que poner un valor explícito.

**`start` de PicCap devuelve `{"returnValue":false}` si ya está corriendo.**
Eso no es un fallo. Confirmar con `status`, no con el valor de `start`.

**Métodos luna reales de PicCap:** `getSettings`, `setSettings`, `start`,
`stop`, **`status`**. No existen `isRunning`, `isRoot`, `getStatus`,
`getState` — devuelven "Unknown method".

**Con `rgbwm: 2` (Accurate), WLED calcula el canal W desde el RGB e ignora el W
que le mandes a mano.** Mandar `col: [[0,0,0,255]]` deja la tira **apagada**.
El blanco se manda como `[255,255,255,0]`.

**La API de HyperHDR aplica en vivo pero no persiste.** `adjustment` y
`componentstate` se pierden al reiniciar. Para persistir: parar HyperHDR →
escribir SQLite → arrancarlo → **reiniciar PicCap**, en ese orden.

**Resolver mDNS cuesta ~3 s por petición.** Por eso `server.py` cachea la IP
resuelta y solo vuelve a resolver si una petición falla.

**PicCap necesita root.** Arranca como uid 5812 y `vtcapture` lo rechaza:

```sh
/media/developer/apps/usr/palm/services/org.webosbrew.hbchannel.service/elevate-service org.webosbrew.piccap.service
```

Verificar con `grep ^Uid /proc/<pid>/status` → debe ser 0.

## Memoria de la TV

`free -m` muestra ~1615 MB usados de 1971, ~85 libres y **455 MB en swap**.
Carga promedio sostenida ~15.

El reparto real: **WebAppMgr ~398 MB** en tres instancias + **Netflix 117 MB**
+ Luma 51 MB. **Todo el stack de homebrew suma ~52 MB.**

> Si hay presión de memoria, el culpable es el runtime de apps web de LG.
> No perseguir ahí.

## DRM

**Netflix, Apple TV y Disney+ no llegan a la tira.**

Medido: con Netflix en primer plano, los 180 LEDs leen `(0,0,0)` exacto, tres
muestras seguidas, cero variación entre ellos. Una escena oscura real daría
valores bajos pero **distintos**.

webOS decodifica el contenido protegido en una región de memoria segura que la
CPU normal no puede leer. `vtcapture` recibe un plano vacío. **Ninguna app del
catálogo de Homebrew lo arregla** (62 apps revisadas; las únicas de ambilight
son PicCap, HyperHDR y Hyperion.NG). El bloqueo está debajo de la capa de apps.

### Opciones

**Ver desde la PC** — funciona, el ambilight pasa completo. Pero **se pierde
Dolby Vision**.

**HyperDRM** (`matze19999/HyperDRM`, fuera del catálogo) — no captura frames:
lee el **histograma** de 16 regiones por una API que LG no bloquea porque
entrega estadísticas, no imagen. Tiene modo *Auto PicCap* que cede la captura a
PicCap cuando no hay DRM, así que no se pierde calidad en el resto.

Requisitos **ya verificados en este C2**: glibc **2.39** (pide ≥ 2.34) ✓ y la
clase **`VtHistogram` presente** en `/usr/lib/libvtcapture.so.1` ✓ — justo lo
que le faltaba al C1, reportado incompatible.

Riesgo: su calibración espacial solo está validada en el G4. En otros modelos
puede degradarse a **un color promedio único** para toda la tira.

**Capturadora HDMI** — divisor que quita HDCP + capturadora USB + HyperHDR en
otro equipo. Calidad completa, funciona con todo. Pero la mayoría de los
divisores que quitan HDCP **también tumban el Dolby Vision**.
