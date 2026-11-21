#!/usr/bin/env bash
# Despliega el panel de ambilight en Proxmox como servicio systemd.
#
#   ./deploy.sh --crear 110   -> crea el LXC 110 y lo instala dentro
#   ./deploy.sh --ct 110      -> instala en el LXC 110 (ya existente)
#   ./deploy.sh               -> instala en el propio host Proxmox
#
# Deja el servicio escuchando en el puerto 8777 de toda la red, para poder
# abrirlo desde el celular. Genera una llave ssh propia para hablarle a la TV;
# al final imprime la llave publica, que hay que autorizar en la TV.
set -euo pipefail

MODO=host
CT=""
case "${1:-}" in
  --crear) MODO=crear; CT="${2:?falta el numero de contenedor, ej: --crear 110}" ;;
  --ct)    MODO=ct;    CT="${2:?falta el numero de contenedor, ej: --ct 110}" ;;
  "")      MODO=host ;;
  *) echo "Uso: $0 [--crear CTID | --ct CTID]"; exit 1 ;;
esac

TV="${AMBI_TV:-192.168.1.10}"
WLED="${AMBI_WLED:-wled-xxxxxx.local}"
PORT="${AMBI_PORT:-8777}"
ALMACEN="${AMBI_STORAGE:-local-lvm}"   # donde vive el disco del contenedor
PUENTE="${AMBI_BRIDGE:-vmbr0}"
DEST=/opt/ambilight
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

say(){ printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
err(){ printf '\n\033[1;31m!! %s\033[0m\n' "$*" >&2; }

# ---------------------------------------------------------------- crear LXC
if [[ "$MODO" == crear ]]; then
  say "Creando contenedor LXC $CT"
  if pct status "$CT" &>/dev/null; then
    err "El contenedor $CT ya existe. Usa --ct $CT para instalar dentro."; exit 1
  fi

  # Reutiliza la plantilla Debian mas reciente que ya este descargada.
  PLANTILLA=$(pveam list local 2>/dev/null | awk '/debian-1[0-9]/{print $1}' | sort -V | tail -1 || true)
  if [[ -z "$PLANTILLA" ]]; then
    say "No hay plantilla Debian local; descargando"
    DISPONIBLE=$(pveam available --section system | awk '/debian-1[0-9]-standard/{print $2}' | sort -V | tail -1)
    [[ -n "$DISPONIBLE" ]] || { err "No encontre plantilla Debian en el catalogo. Corre: pveam update"; exit 1; }
    pveam download local "$DISPONIBLE"
    PLANTILLA="local:vztmpl/$DISPONIBLE"
  fi
  echo "    plantilla: $PLANTILLA"

  pct create "$CT" "$PLANTILLA" \
    --hostname ambilight \
    --cores 1 --memory 512 --swap 256 \
    --rootfs "$ALMACEN:2" \
    --net0 "name=eth0,bridge=$PUENTE,ip=dhcp" \
    --features nesting=1 \
    --onboot 1 \
    --unprivileged 1 \
    --description "Panel de control del ambilight (HyperHDR + PicCap + WLED)"

  pct start "$CT"
  say "Esperando red del contenedor"
  for _ in $(seq 1 30); do
    pct exec "$CT" -- getent hosts deb.debian.org &>/dev/null && break
    sleep 2
  done
  MODO=ct
fi

# ------------------------------------------------- capa unica host vs LXC
if [[ "$MODO" == ct ]]; then
  run(){ pct exec "$CT" -- bash -lc "$*"; }
  put(){ pct push "$CT" "$1" "$2" --perms 644; }
  say "Objetivo: contenedor LXC $CT"
  pct status "$CT" | grep -q running || { err "El contenedor $CT no esta corriendo."; exit 1; }
else
  run(){ bash -lc "$*"; }
  put(){ install -m 644 "$1" "$2"; }
  say "Objetivo: host Proxmox ($(hostname))"
fi

say "Dependencias"
run "command -v python3 >/dev/null && command -v ssh >/dev/null || (apt-get update -qq && apt-get install -y -qq python3 openssh-client)"
run "python3 --version; ssh -V 2>&1 | head -1"

say "Archivos en $DEST"
run "mkdir -p $DEST"
put "$SRC/server.py"  "$DEST/server.py"
put "$SRC/index.html" "$DEST/index.html"
run "chmod 755 $DEST/server.py"

say "Llave ssh del servicio"
# Sin passphrase porque es un servicio desatendido. El alcance se limita
# autorizandola solo en la TV, el unico equipo al que necesita entrar.
run "test -f $DEST/id_tv || ssh-keygen -t ed25519 -N '' -C ambilight-panel -f $DEST/id_tv -q"
run "chmod 600 $DEST/id_tv"
PUB=$(run "cat $DEST/id_tv.pub" | tr -d '\r')

say "Servicio systemd"
TMP=$(mktemp)
cat > "$TMP" <<UNITEOF
[Unit]
Description=Panel de control del ambilight (HyperHDR + PicCap + WLED)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$DEST
Environment=AMBI_TV=$TV
Environment=AMBI_WLED=$WLED
Environment=AMBI_PORT=$PORT
Environment=AMBI_BIND=0.0.0.0
Environment=AMBI_SSH_KEY=$DEST/id_tv
ExecStart=/usr/bin/python3 $DEST/server.py
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
UNITEOF
put "$TMP" /etc/systemd/system/ambilight.service
rm -f "$TMP"

run "systemctl daemon-reload && systemctl enable --now ambilight.service"
sleep 3
run "systemctl is-active ambilight.service" || err "El servicio no quedo activo; revisa: journalctl -u ambilight -n 40"

say "Direccion"
if [[ "$MODO" == ct ]]; then
  IP=$(run "hostname -I | awk '{print \$1}'" | tr -d '\r')
else
  IP=$(hostname -I | awk '{print $1}')
fi
echo "    http://$IP:$PORT"

say "FALTA UN PASO: autorizar esta llave en la TV"
echo "$PUB"
echo
echo "Desde un equipo que ya entre a la TV:"
echo "    echo '$PUB' | ssh root@$TV 'cat >> /home/root/.ssh/authorized_keys'"
echo
echo "Sin eso el panel muestra el estado, pero no puede reiniciar PicCap ni guardar."
