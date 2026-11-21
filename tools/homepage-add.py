#!/usr/bin/env python3
"""Agrega la entrada de Ambilight al services.yaml de Homepage.

Idempotente: si ya existe, no duplica. Deja respaldo con fecha.
Se inserta al final del grupo Infraestructura, justo antes de Respaldo.
"""
import datetime
import shutil
import sys

RUTA = "/app/config/services.yaml"

ENTRADA = """    - Ambilight:
        icon: mdi-led-strip-variant
        href: http://192.168.1.20:8777
        description: Luz detras de la TV
        siteMonitor: http://192.168.1.20:8777
        widget:
          type: customapi
          url: http://192.168.1.20:8777/api/estado
          refreshInterval: 10000
          mappings:
            - field: cadena
              label: Estado
            - field:
                piccap: fps
              label: Captura
              format: number
              suffix: " fps"
            - field:
                wled: fps
              label: Tira
              format: number
              suffix: " fps"
            - field:
                wled: pwr
              label: Consumo
              format: number
              suffix: " mA"
"""

texto = open(RUTA, encoding="utf-8").read()

if "Ambilight:" in texto:
    print("ya existe, no se toca")
    sys.exit(0)

ancla = "\n- Respaldo:"
if ancla not in texto:
    print("ERROR: no encontre el grupo Respaldo para anclar la insercion")
    sys.exit(1)

sello = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
shutil.copy(RUTA, RUTA + ".bak-ambilight-" + sello)

texto = texto.replace(ancla, "\n" + ENTRADA + ancla, 1)
open(RUTA, "w", encoding="utf-8").write(texto)
print("agregado; respaldo en services.yaml.bak-ambilight-" + sello)
