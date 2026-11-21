#!/usr/bin/env python3
"""Genera el layout de LEDs de HyperHDR y lo escribe en su base de datos.

Se corre EN LA TV, con HyperHDR DETENIDO (si no, reescribe la base al salir):

    luna-send -n 1 -w 5000 luna://org.webosbrew.hyperhdr.loader.service/stop '{}'
    sleep 4
    python3 layout.py
    luna-send -n 1 -w 8000 luna://org.webosbrew.hyperhdr.loader.service/start '{}'
    # y despues reiniciar PicCap, que no reconecta solo

Montaje asumido: sentido horario desde la esquina INFERIOR IZQUIERDA.
Sube por la izquierda, cruza arriba de izq a der, baja por la derecha.
Sin orilla inferior.
"""
import datetime
import json
import shutil
import sqlite3

DB = "/home/root/.config/HyperHDR/db/hyperhdr.db"

LEFT, TOP, RIGHT = 48, 84, 48
DEPTH = 0.08          # que tan adentro de la pantalla muestrea cada LED (8 %)


def construye():
    """En HyperHDR, v va de 0 (arriba) a 1 (abajo)."""
    leds = []
    # 1) columna izquierda, de ABAJO hacia ARRIBA
    for i in range(LEFT):
        leds.append({"group": 0, "hmin": 0.0, "hmax": DEPTH,
                     "vmin": round(1 - (i + 1) / LEFT, 4),
                     "vmax": round(1 - i / LEFT, 4)})
    # 2) fila superior, de IZQUIERDA a DERECHA
    for j in range(TOP):
        leds.append({"group": 0,
                     "hmin": round(j / TOP, 4), "hmax": round((j + 1) / TOP, 4),
                     "vmin": 0.0, "vmax": DEPTH})
    # 3) columna derecha, de ARRIBA hacia ABAJO
    for k in range(RIGHT):
        leds.append({"group": 0, "hmin": round(1 - DEPTH, 4), "hmax": 1.0,
                     "vmin": round(k / RIGHT, 4),
                     "vmax": round((k + 1) / RIGHT, 4)})
    return leds


def main():
    leds = construye()
    total = LEFT + TOP + RIGHT
    assert len(leds) == total, len(leds)

    sello = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    shutil.copy(DB, DB + ".bak-layout-" + sello)

    con = sqlite3.connect(DB)
    stamp = "strftime('%Y-%m-%dT%H:%M:%SZ','now')"
    con.execute("update settings set config=?, updated_at=" + stamp +
                " where type='leds'", (json.dumps(leds),))

    # Que el generador 'classic' de la interfaz refleje lo mismo.
    lc = json.loads(list(con.execute(
        "select config from settings where type='ledConfig'"))[0][0])
    lc.setdefault("classic", {}).update({
        "top": TOP, "bottom": 0, "left": LEFT, "right": RIGHT,
        "glength": 0, "gpos": 0, "position": 0, "reverse": False,
        "hdepth": int(DEPTH * 100), "vdepth": int(DEPTH * 100),
        "overlap": 0, "edgegap": 0})
    con.execute("update settings set config=?, updated_at=" + stamp +
                " where type='ledConfig'", (json.dumps(lc),))
    con.commit()

    print("leds escritos      :", total)
    print("  LED 0   abajo-izq:", json.dumps(leds[0]))
    print("  LED %-3d arriba-izq:" % LEFT, json.dumps(leds[LEFT]))
    print("  LED %-3d arriba-der:" % (LEFT + TOP - 1),
          json.dumps(leds[LEFT + TOP - 1]))
    print("  LED %-3d abajo-der :" % (total - 1), json.dumps(leds[-1]))
    print("respaldo           :", DB + ".bak-layout-" + sello)


if __name__ == "__main__":
    main()
