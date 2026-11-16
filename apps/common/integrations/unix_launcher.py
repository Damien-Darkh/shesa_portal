"""unix_launcher.py - Company Network setup for macOS and Linux.

Each generated installer does three things, in this order:
  1. Creates a NAS shortcut or mount point, and installs a sign-out cleanup that
     removes NAS mounts and saved passwords on sign-out, shutdown or restart.
  2. Installs WireGuard (wireguard-tools) if needed and imports the tunnel.
  3. Asks the user whether to enable the tunnel now, then verifies the handshake
     and the NAS SMB port when it is enabled.

The private key lives only in the generated script, which is served once and
then wiped by the device endpoint.
"""
import re

_IPV4_RE = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}$")
_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,15}$")  # wg-quick interface names are short

# ============================================================
# Sign-out cleanup (shared by both platforms)
# ============================================================

MACOS_CLEANUP = r"""#!/bin/bash
# nas-logout.sh - removes NAS mounts and saved passwords for one user.
# Runs as root from the login window LogoutHook (sign-out, shutdown, restart).
NAS_IP="__NAS_IP__"
TARGET_USER="__TARGET_USER__"
LOG="/var/log/companynetwork-nas-logout.log"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"; }

# The hook runs for every user. Act only when the configured user is the one signing out.
if [ -z "$TARGET_USER" ] || [ "$(/usr/bin/stat -f%Su /dev/console 2>/dev/null)" != "$TARGET_USER" ]; then
  exit 0
fi

# 1. Unmount SMB shares from the NAS.
mount -t smbfs 2>/dev/null | grep -F "$NAS_IP" | sed -E 's/^.* on (.*) \(smbfs.*$/\1/' |
while IFS= read -r mountpoint; do
  if umount "$mountpoint" 2>/dev/null || umount -f "$mountpoint" 2>/dev/null; then
    log "unmounted $mountpoint"
  else
    log "could not unmount $mountpoint"
  fi
done

# 2. Remove saved SMB passwords from the user's keychain (best effort).
uid="$(id -u "$TARGET_USER")"
for _ in 1 2 3 4 5; do
  launchctl asuser "$uid" sudo -u "$TARGET_USER" /usr/bin/security \
    delete-internet-password -s "$NAS_IP" >/dev/null 2>&1 || break
done
log "keychain cleanup finished for $NAS_IP"
exit 0
"""

LINUX_CLEANUP = r"""#!/bin/bash
# nas-logout.sh - removes NAS mounts and saved passwords for the current user.
# Runs from the systemd user service when the session ends.
NAS_IP="__NAS_IP__"
LOG="${XDG_STATE_HOME:-$HOME/.local/state}/companynetwork/nas-logout.log"
mkdir -p "$(dirname "$LOG")"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"; }

# 1. GVFS mounts (GNOME and KDE file managers).
if command -v gio >/dev/null 2>&1; then
  gio mount -li 2>/dev/null | grep -oE "smb://${NAS_IP}[^[:space:]]*" | sort -u |
  while IFS= read -r uri; do
    gio mount -u "$uri" 2>/dev/null && log "unmounted $uri"
  done
fi

# 2. Kernel CIFS mounts made for this session.
findmnt -rn -t cifs,smb3 -o TARGET,SOURCE 2>/dev/null | grep -F "//${NAS_IP}/" | cut -d' ' -f1 |
while IFS= read -r mountpoint; do
  umount -l "$mountpoint" 2>/dev/null && log "unmounted $mountpoint"
done

# 3. Saved SMB passwords in the desktop keyring (best effort).
if command -v secret-tool >/dev/null 2>&1; then
  secret-tool clear protocol smb server "$NAS_IP" 2>/dev/null && log "keyring entry cleared"
fi

log "cleanup finished for $NAS_IP"
exit 0
"""

# ============================================================
# macOS installer
# ============================================================

MACOS_INSTALLER = r"""#!/bin/bash
# Company Network - setup for macOS. Double-click the .command file, or run: bash "<file>.command"
set -uo pipefail

# ---------- Administrator permission (one prompt) ----------
if [ "$(id -u)" -ne 0 ]; then
  echo "Administrator permission is needed to install the company network setup."
  exec sudo /bin/bash "$0"
fi

TARGET_USER="${SUDO_USER:-}"
if [ -z "$TARGET_USER" ] || [ "$TARGET_USER" = "root" ]; then
  echo "Run this file from the account you sign in with."
  exit 1
fi
TARGET_HOME="$(dscl . -read "/Users/$TARGET_USER" NFSHomeDirectory 2>/dev/null | awk '{print $2}')"

say()  { echo "$*"; }
fail() { echo ""; echo "Setup failed: $*"; echo "Log: /var/log/companynetwork-setup.log"; exit 1; }
exec > >(tee -a /var/log/companynetwork-setup.log) 2>&1

NAS_IP="__NAS_IP__"
WG_NAME="__TUNNEL_NAME__"
WG_CONF_DIR="$(brew --prefix 2>/dev/null || echo /usr/local)/etc/wireguard"
[ -d /opt/homebrew ] && WG_CONF_DIR="/opt/homebrew/etc/wireguard"
WG_CONF="$WG_CONF_DIR/$WG_NAME.conf"

# ---------- 1. Desktop shortcut to the NAS ----------
# Finder cannot pin a SMB address in a file, so the shortcut is a .webloc to smb://.
DESKTOP="$TARGET_HOME/Desktop"
if [ -d "$DESKTOP" ] && [ ! -e "$DESKTOP/SHESA.webloc" ]; then
  cat > "$DESKTOP/SHESA.webloc" <<WEBLOC
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict><key>URL</key><string>smb://$NAS_IP</string></dict></plist>
WEBLOC
  chown "$TARGET_USER" "$DESKTOP/SHESA.webloc"
  say "Desktop shortcut created."
fi

# ---------- 2. Sign-out cleanup ----------
DEST_DIR="/Library/Application Support/CompanyNetwork"
mkdir -p "$DEST_DIR"
cat > "$DEST_DIR/nas-logout.sh" <<'NASLOGOUT'
__CLEANUP__
NASLOGOUT
sed -i '' "s/^TARGET_USER=.*/TARGET_USER=\"$TARGET_USER\"/" "$DEST_DIR/nas-logout.sh"
chown root:wheel "$DEST_DIR/nas-logout.sh"
chmod 755 "$DEST_DIR/nas-logout.sh"
defaults write com.apple.loginwindow LogoutHook "$DEST_DIR/nas-logout.sh"
say "Sign-out cleanup installed."

# ---------- 3. WireGuard ----------
if ! command -v wg-quick >/dev/null 2>&1; then
  BREW="$(command -v brew || true)"
  [ -z "$BREW" ] && [ -x /opt/homebrew/bin/brew ] && BREW=/opt/homebrew/bin/brew
  [ -z "$BREW" ] && [ -x /usr/local/bin/brew ] && BREW=/usr/local/bin/brew
  if [ -z "$BREW" ]; then
    fail "Homebrew is needed to install WireGuard. Install it from https://brew.sh, then run this file again."
  fi
  say "Installing WireGuard tools..."
  sudo -u "$TARGET_USER" "$BREW" install wireguard-tools >/dev/null 2>&1 \
    || fail "Could not install wireguard-tools with Homebrew."
fi
WG_QUICK="$(command -v wg-quick || echo /opt/homebrew/bin/wg-quick)"
WG_BIN="$(command -v wg || echo /opt/homebrew/bin/wg)"

# ---------- 4. Import the tunnel ----------
mkdir -p "$WG_CONF_DIR"
cat > "$WG_CONF" <<'WGCONF'
[Interface]
PrivateKey = __WG_PRIVATE_KEY__
Address = __WG_ADDRESS__
DNS = __WG_DNS__

[Peer]
PublicKey = __WG_PEER_PUBLIC_KEY__
PresharedKey = __WG_PRESHARED_KEY__
Endpoint = __WG_ENDPOINT__
AllowedIPs = __WG_ALLOWED_IPS__
PersistentKeepalive = __WG_KEEPALIVE__
WGCONF
chmod 600 "$WG_CONF"
say "Tunnel imported."

# ---------- 5. Choose ----------
say ""
say "Do you want to connect to the company network now?"
say "  y  - connect now (needed when working remotely)"
say "  n  - keep the tunnel installed but disconnected"
read -r -p "Connect now? [y/N] " answer </dev/tty || answer="n"

if [[ "$answer" =~ ^[Yy]$ ]]; then
  "$WG_QUICK" up "$WG_NAME" || fail "wg-quick could not bring up the tunnel."

  # Verify the handshake.
  handshake=0
  for _ in $(seq 1 15); do
    ts="$("$WG_BIN" show "$WG_NAME" latest-handshakes 2>/dev/null | awk '{print $2}' | head -n1)"
    if [ -n "$ts" ] && [ "$ts" -gt 0 ] 2>/dev/null; then handshake=1; break; fi
    sleep 2
  done
  [ "$handshake" -eq 1 ] || fail "The VPN has no active handshake. Check that $WG_NAME can reach the endpoint."

  # Verify the NAS SMB port.
  if nc -z -G 5 "$NAS_IP" 445 >/dev/null 2>&1; then
    say "Connected. The company file server is reachable."
  else
    fail "VPN connected, but $NAS_IP does not answer on the file-sharing port."
  fi
else
  say "Tunnel left disconnected. To connect later, run: sudo wg-quick up $WG_NAME"
fi

say ""
say "Setup complete."
"""

# ============================================================
# Linux installer
# ============================================================

LINUX_INSTALLER = r"""#!/bin/bash
# Company Network - setup for Linux. Run as your own user: bash setup-company-network.sh
# It asks for your password once when it needs root.
set -uo pipefail

if [ "$(id -u)" -eq 0 ]; then
  echo "Run this as your own user, not as root. The script asks for sudo when it needs it."
  exit 1
fi

NAS_IP="__NAS_IP__"
WG_NAME="__TUNNEL_NAME__"
WG_CONF="/etc/wireguard/$WG_NAME.conf"
LOG="${XDG_STATE_HOME:-$HOME/.local/state}/companynetwork/setup.log"
mkdir -p "$(dirname "$LOG")"

say()  { echo "$*"; }
log()  { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"; }
fail() { echo ""; echo "Setup failed: $*"; echo "Log: $LOG"; log "FAILED: $*"; exit 1; }

# ---------- 1. Desktop shortcut ----------
DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
if [ -d "$DESKTOP_DIR" ] && [ ! -e "$DESKTOP_DIR/SHESA.desktop" ]; then
  cat > "$DESKTOP_DIR/SHESA.desktop" <<DESK
[Desktop Entry]
Type=Link
Name=SHESA
Comment=Company file server
URL=smb://$NAS_IP
Icon=folder-remote
DESK
  chmod +x "$DESKTOP_DIR/SHESA.desktop"
  say "Desktop shortcut created."
  log "desktop shortcut created"
fi

# ---------- 2. Sign-out cleanup (systemd user service) ----------
BIN_DIR="$HOME/.local/share/companynetwork"
UNIT_DIR="$HOME/.config/systemd/user"
UNIT="companynetwork-nas-logout.service"
mkdir -p "$BIN_DIR" "$UNIT_DIR"

cat > "$BIN_DIR/nas-logout.sh" <<'NASLOGOUT'
__CLEANUP__
NASLOGOUT
chmod 700 "$BIN_DIR/nas-logout.sh"

cat > "$UNIT_DIR/$UNIT" <<UNITFILE
[Unit]
Description=Remove company NAS sessions and saved credentials on sign-out

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/true
ExecStop=/bin/bash %h/.local/share/companynetwork/nas-logout.sh
TimeoutStopSec=30

[Install]
WantedBy=default.target
UNITFILE

if systemctl --user daemon-reload && systemctl --user enable --now "$UNIT" >/dev/null 2>&1; then
  say "Sign-out cleanup installed."
  log "sign-out cleanup installed"
else
  say "Could not install the sign-out cleanup (no user systemd session). Continuing."
  log "WARN: user systemd unavailable"
fi

# ---------- 3. WireGuard ----------
if ! command -v wg-quick >/dev/null 2>&1; then
  say "Installing WireGuard tools (administrator password may be asked)..."
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get install -y wireguard-tools >>"$LOG" 2>&1 || fail "Could not install wireguard-tools."
  elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y wireguard-tools >>"$LOG" 2>&1 || fail "Could not install wireguard-tools."
  elif command -v pacman >/dev/null 2>&1; then
    sudo pacman -S --noconfirm wireguard-tools >>"$LOG" 2>&1 || fail "Could not install wireguard-tools."
  else
    fail "No supported package manager found. Install wireguard-tools, then run this again."
  fi
fi

# ---------- 4. Import the tunnel ----------
sudo mkdir -p /etc/wireguard
sudo tee "$WG_CONF" >/dev/null <<'WGCONF'
[Interface]
PrivateKey = __WG_PRIVATE_KEY__
Address = __WG_ADDRESS__
DNS = __WG_DNS__

[Peer]
PublicKey = __WG_PEER_PUBLIC_KEY__
PresharedKey = __WG_PRESHARED_KEY__
Endpoint = __WG_ENDPOINT__
AllowedIPs = __WG_ALLOWED_IPS__
PersistentKeepalive = __WG_KEEPALIVE__
WGCONF
sudo chmod 600 "$WG_CONF"
say "Tunnel imported."
log "tunnel config written to $WG_CONF"

# ---------- 5. Choose ----------
say ""
say "Do you want to connect to the company network now?"
say "  y  - connect now (needed when working remotely)"
say "  n  - keep the tunnel installed but disconnected"
read -r -p "Connect now? [y/N] " answer </dev/tty || answer="n"

if [[ "$answer" =~ ^[Yy]$ ]]; then
  sudo wg-quick up "$WG_NAME" || fail "wg-quick could not bring up the tunnel."

  handshake=0
  for _ in $(seq 1 15); do
    ts="$(sudo wg show "$WG_NAME" latest-handshakes 2>/dev/null | awk '{print $2}' | head -n1)"
    if [ -n "$ts" ] && [ "$ts" -gt 0 ] 2>/dev/null; then handshake=1; break; fi
    sleep 2
  done
  [ "$handshake" -eq 1 ] || fail "The VPN has no active handshake. Check that the endpoint is reachable."

  if timeout 5 bash -c "</dev/tcp/$NAS_IP/445" 2>/dev/null; then
    say "Connected. The company file server is reachable."
    log "connected; NAS reachable"
  else
    fail "VPN connected, but $NAS_IP does not answer on the file-sharing port."
  fi
else
  say "Tunnel left disconnected. To connect later, run: sudo wg-quick up $WG_NAME"
  log "tunnel installed, left disconnected"
fi

say ""
say "Setup complete."
log "setup complete"
"""


# ============================================================
# Rendering
# ============================================================

def _validate(nas_ip: str, tunnel_name: str) -> None:
    if not _IPV4_RE.match(nas_ip or ""):
        raise ValueError("NAS address must be an IPv4 address.")
    if not _NAME_RE.match(tunnel_name or ""):
        raise ValueError("Tunnel name must be 1-15 letters, digits, '_' or '-'.")


def _fill(template: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        template = template.replace(key, value)
    return template


def _wg_values(tunnel_name: str, nas_ip: str, wg: dict) -> dict[str, str]:
    return {
        "__NAS_IP__": nas_ip,
        "__TUNNEL_NAME__": tunnel_name,
        "__WG_PRIVATE_KEY__": wg["private_key"],
        "__WG_ADDRESS__": wg["address_cidr"],
        "__WG_DNS__": wg["dns"],
        "__WG_PEER_PUBLIC_KEY__": wg["peer_public_key"],
        "__WG_PRESHARED_KEY__": wg["preshared_key"],
        "__WG_ENDPOINT__": wg["endpoint"],
        "__WG_ALLOWED_IPS__": wg["allowed_ips"],
        "__WG_KEEPALIVE__": wg["keepalive"],
    }


def render_macos_installer(nas_ip: str, tunnel_name: str, wg: dict) -> str:
    _validate(nas_ip, tunnel_name)
    cleanup = _fill(MACOS_CLEANUP, {"__NAS_IP__": nas_ip})
    values = _wg_values(tunnel_name, nas_ip, wg)
    values["__CLEANUP__"] = cleanup
    return _fill(MACOS_INSTALLER, values)


def render_linux_installer(nas_ip: str, tunnel_name: str, wg: dict) -> str:
    _validate(nas_ip, tunnel_name)
    cleanup = _fill(LINUX_CLEANUP, {"__NAS_IP__": nas_ip})
    values = _wg_values(tunnel_name, nas_ip, wg)
    values["__CLEANUP__"] = cleanup
    return _fill(LINUX_INSTALLER, values)