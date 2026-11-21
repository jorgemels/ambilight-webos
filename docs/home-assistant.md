# Integración con Home Assistant

HA está en `192.168.1.30:8123`. Todo se agregó a `configuration.yaml`.

## Entidades

### Sensores (`rest`, sondea `/api/estado` cada 30 s)

| Entidad | Unidad |
|---|---|
| `binary_sensor.ambilight_cadena` | `on` = activa · `device_class: running` |
| `binary_sensor.ambilight_vigilante` | `on` = reparación automática activa |
| `sensor.ambilight_captura` | fps de PicCap |
| `sensor.ambilight_tira` | fps de WLED |
| `sensor.ambilight_consumo` | mA |
| `sensor.ambilight_brillo` | % |

### Interruptores (`command_line`, con estado real)

| Entidad | Qué hace |
|---|---|
| `switch.ambilight_vigilante` | Reparación automática |
| `switch.ambilight_suavizado` | Componente `SMOOTHING` de HyperHDR |
| `switch.ambilight_encendido` | Corta la salida a la tira sin tocar HyperHDR |

### Acciones (`shell_command`)

| Acción | Parámetro |
|---|---|
| `shell_command.ambilight_reiniciar_piccap` | — |
| `shell_command.ambilight_brillo` | `valor` (0–1) |
| `shell_command.ambilight_piso_de_luz` | `valor` |
| `shell_command.ambilight_preset` | `nombre` |

## Por qué no se usó `rest_command`

No está en la lista de claves permitidas del servidor MCP de HA. Las permitidas
son: `binary_sensor`, `climate`, `command_line`, `cover`, `fan`, `group`,
`knx`, `light`, `mqtt`, `notify`, `recorder`, `rest`, `sensor`,
`shell_command`, `switch`, `template`, `utility_meter`.

Salió mejor: `command_line` crea **interruptores con estado real** que leen la
situación de vuelta, no solo botones que disparan y no saben en qué quedó.

## Recargas

> Una clave **nueva** en `configuration.yaml` exige **reinicio completo de HA**.
> No hay servicio de recarga para una integración que nunca se cargó.

Ya cargada, basta `shell_command.reload` / `command_line.reload` / `rest.reload`.

Tras reiniciar HA, los `command_line` switches salen en `off` en el primer
sondeo. **No es un bug**: aún no ha corrido `command_state`. Se corrigen solos
en 30 s.

`curl` sí existe en el contenedor de HA.

## Ejemplos de automatización

Bajar el brillo de noche:

```yaml
alias: Ambilight nocturno
triggers:
  - trigger: time
    at: "23:00:00"
conditions: []
actions:
  - action: shell_command.ambilight_preset
    data:
      nombre: Noche
mode: single
```

Avisar si el vigilante no pudo reparar la cadena:

```yaml
alias: Ambilight caído
triggers:
  - trigger: state
    entity_id: binary_sensor.ambilight_cadena
    to: "off"
    for: "00:05:00"
conditions: []
actions:
  - action: notify.mobile_app_TU_TELEFONO
    data:
      message: >-
        El ambilight lleva 5 minutos caído y la reparación automática
        no lo resolvió.
mode: single
```

Cinco minutos es deliberado: el vigilante actúa a los ~60 s y espera hasta
5 min entre intentos. Avisar antes daría falsas alarmas de algo que se iba a
arreglar solo.

## Nota

La configuración de HA contiene un token de acceso de larga duración para el
widget de Homepage. **No está en este repositorio** y no debe copiarse aquí.
