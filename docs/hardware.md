# Hardware

## Tira

**SK6812 RGBNW**, 3 m, 60 LED/m, IP30, PCB negro → **180 LEDs**, 5 V.

Cómo se identifica (por si hay que repetirlo con otra tira): el encapsulado
tiene **dos zonas** — arriba un fósforo **amarillo**, que es un LED blanco
dedicado, y abajo los chips R/G/B. Una WS2812B solo tiene 3 chips y nada de
amarillo. Esa diferencia decide `LED type` en WLED y no es opcional:

> Con `WS281x` el controlador manda **24 bits por LED** y la tira espera **32**.
> El resultado es un desfase progresivo: los primeros LEDs responden más o menos
> y de ahí los colores se van corriendo. Parece tira defectuosa y no lo es.

La serigrafía del PCB dice `+5V` / `Din` / `GND` y trae **flechas** que marcan
la dirección de los datos.

### Ambos extremos traen conector

- Extremo **`Din`** → entrada. **Aquí va el controlador.**
- Extremo **`DO`** → salida. Sirve para encadenar otra tira, o para inyectar
  corriente desde la fuente.

No guiarse por macho/hembra: varía entre fabricantes. **Guiarse por la
serigrafía y las flechas** — deben apuntar *alejándose* del extremo donde se
conecta. Si se conecta al revés no enciende nada, pero no se daña.

Cada extremo trae 5 cables: 3 delgados al conector JST (`+5V`, `Din`/`DO`,
`GND`) y 2 gruesos de inyección de corriente (`+5V`, `GND`).

> Los colores del aislante **no son confiables**. Para identificarlos hay que
> seguir cada cable hasta su pad en el PCB. El reparto correcto es **2–1–2**:
> dos cables en `+5V`, uno en datos, dos en `GND`.

## Controlador

**GLEDOPTO Elite 2D-EXMU** (`GL-C-I-616WL(PDM)`), ESP32 con WLED.
Entrada `DC 5-12-24V`, 15 A máx, puerto USB-C y **puerto Ethernet**.

La serigrafía se lee "ZD-EXMU" pero el carácter es un **2**.
Manual oficial (escaneado, sin texto extraíble):
<https://www.gledopto.com/616wl-manual-en.pdf>

### Bornera

De izquierda a derecha, con corchetes impresos que agrupan cada salida:

| # | Etiqueta | Palanca | Uso |
|---|---|---|---|
| 1 | `GND` | negra | tierra auxiliar |
| 2 | `IO13` | **blanca** | señal auxiliar — **sin usar** |
| 3 | `GND` | negra | tierra salida 2 |
| 4 | `IO2` | azul | datos salida 2 |
| 5 | `V+` | roja | positivo salida 2 |
| 6 | `GND` | negra | **tierra salida 1** |
| 7 | `IO16` | azul | **datos salida 1** |
| 8 | `V+` | roja | **positivo salida 1** |

Código de color: **rojo = V+, azul = datos, negro = GND, blanca = auxiliar**.

Pelar **10 mm**. Acepta **0.34–4 mm² (22–12 AWG)**.
Etiqueta interna de la bornera: `Mini 297`.

> **`V+` saca exactamente lo que entra.** No hay regulador. Si la fuente es de
> 12 V y la tira de 5 V, se quema completa al instante.

## Cableado

Los 5 cables del extremo `Din` entran en **3 bornes**:

| Cables | Borne |
|---|---|
| 🔴 rojo delgado **+** 🔴 rojo grueso | `V+` (#8) |
| 🟢 datos | `IO16` (#7) |
| ⚪ blanco delgado **+** ⚪ blanco grueso | `GND` (#6) |

Trenzar cada par antes de meterlo. Que no asome cobre fuera del borne: un hilo
suelto entre `V+` y `GND` es un corto de 15 A y la fuente no tiene cómo saber
que está mal.

No hace falta estañar. Estas borneras son para cable desnudo, y el estaño se
escurre bajo presión con el tiempo y afloja la conexión.

### Inyección de corriente

El par grueso del extremo `Din` sale del mismo punto que el conector, así que
conectarlo ahí solo engrosa la alimentación — ayuda, pero no es inyección real.

La inyección de verdad usa el par grueso del extremo **`DO`**, llevado
**directo a la fuente**, nunca al controlador (haría pasar toda la corriente
por el controlador otra vez, sin ganancia y cargándolo de más).

Con 3 m y ~2.9 A en blanco, probablemente no haga falta. Se verifica poniendo
blanco a brillo alto y mirando si el extremo lejano se ve más tenue o tira a
amarillo/rosa.

## Consumo

180 LEDs RGBW a 80 mA = 14.4 A teóricos con los cuatro canales al máximo.
El límite de WLED en 12000 mA deja margen.

En la práctica el blanco consume **~2.9 A**, no 14, porque en modo `Accurate`
sale casi todo por el canal W dedicado en vez de encender los tres colores.

## Layout

Montaje: **sentido horario desde la esquina inferior izquierda** — sube por la
izquierda, cruza arriba de izquierda a derecha, baja por la derecha. Sin
orilla inferior.

Área activa del 65" 16:9: **143.9 × 80.9 cm**. Tres lados suman 305.7 cm contra
300 cm de tira, o sea 5.7 cm corto. El déficit se repartió proporcionalmente en
vez de dejar que se acumulara al final:

| Lado | cm | LEDs |
|---|---|---|
| Izquierdo (subiendo) | 80.9 | **48** |
| Superior (izq → der) | 143.9 | **84** |
| Derecho (bajando) | 80.9 | **48** |
| | | **180** |

Verificación por índice: LED 0 = abajo-izquierda · 48 = arriba-izquierda ·
131 = arriba-derecha · 179 = abajo-derecha. En el layout de HyperHDR `v` va de
0 arriba a 1 abajo.

El generador está en [`../tools/layout.py`](../tools/layout.py).
Se corre **con HyperHDR detenido** y luego hay que reiniciar PicCap.
