#!/usr/bin/env python3
"""Sonda: ve que manda HyperHDR por su WebSocket al pedir el stream de LEDs."""
import json
import websocket

ws = websocket.create_connection("ws://192.168.1.10:8090/", timeout=10)
ws.send(json.dumps({"command": "ledcolors", "subcommand": "ledstream-start",
                    "tan": 1}))

for i in range(6):
    try:
        msg = json.loads(ws.recv())
    except Exception as exc:
        print("recv error:", exc)
        break
    cmd = msg.get("command")
    res = msg.get("result") or {}
    leds = res.get("leds")
    if leds is None:
        print("%d) %s -> %s" % (i, cmd, json.dumps(msg)[:160]))
    else:
        print("%d) %s -> %d valores (%d leds), primeros 9: %s"
              % (i, cmd, len(leds), len(leds) // 3, leds[:9]))

ws.send(json.dumps({"command": "ledcolors", "subcommand": "ledstream-stop",
                    "tan": 2}))
ws.close()
print("listo")
