#!/usr/bin/env bash
# Installe la surveillance HOKA sur ton ordinateur (Mac ou Raspberry Pi / Linux)
# et la lance automatiquement toutes les 15 minutes depuis ta connexion internet.
#
#   ./install.sh TON-TOPIC-NTFY     installe (ou met à jour) et lance un premier passage
#   ./install.sh --uninstall        arrête et supprime la tâche automatique
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
DATA_DIR="$HOME/.hoka-run-watcher"
VENV="$APP_DIR/.venv"
LABEL="com.hoka-run-watcher"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
OS="$(uname -s)"

if [ "${1:-}" = "--uninstall" ]; then
  if [ "$OS" = "Darwin" ]; then
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
  else
    { crontab -l 2>/dev/null | grep -v "hoka-run-watcher/run.sh" || true; } | crontab -
  fi
  echo "✅ Surveillance locale arrêtée. (Les données restent dans $DATA_DIR)"
  exit 0
fi

TOPIC="${1:-}"
if [ -z "$TOPIC" ]; then
  echo "Usage : ./install.sh TON-TOPIC-NTFY" >&2
  exit 1
fi

echo "▶ Dossier du projet : $APP_DIR"
command -v python3 >/dev/null || { echo "❌ python3 introuvable. Sur Mac : xcode-select --install" >&2; exit 1; }
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' \
  || { echo "❌ Python 3.9 ou plus récent requis." >&2; exit 1; }

echo "▶ Installation de Python + Playwright (quelques minutes la première fois)…"
[ -d "$VENV" ] || python3 -m venv "$VENV"
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -r "$APP_DIR/requirements.txt"
if [ "$OS" = "Linux" ]; then
  echo "▶ Bibliothèques système pour Chromium (mot de passe sudo possible)…"
  sudo "$VENV/bin/python" -m playwright install-deps chromium
fi
"$VENV/bin/python" -m playwright install chromium

mkdir -p "$DATA_DIR"
# Petit lanceur : l'état est gardé hors du dépôt pour que « git pull » reste propre.
cat > "$DATA_DIR/run.sh" <<EOF
#!/usr/bin/env bash
export NTFY_TOPIC="$TOPIC"
export STATE_FILE="$DATA_DIR/state.json"
export BLOCKED_FILE="$DATA_DIR/blocked_count"
export DEBUG_DIR="$DATA_DIR/debug"
cd "$APP_DIR"
echo "=== \$(date '+%Y-%m-%d %H:%M:%S')"
exec "$VENV/bin/python" watch.py
EOF
chmod 700 "$DATA_DIR/run.sh"

echo "▶ Premier passage…"
"$DATA_DIR/run.sh" || true

if [ "$OS" = "Darwin" ]; then
  mkdir -p "$HOME/Library/LaunchAgents"
  cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>$DATA_DIR/run.sh</string></array>
  <key>StartInterval</key><integer>900</integer>
  <key>StandardOutPath</key><string>$DATA_DIR/watch.log</string>
  <key>StandardErrorPath</key><string>$DATA_DIR/watch.log</string>
</dict>
</plist>
EOF
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$PLIST"
  echo "✅ Installé : ton Mac vérifiera toutes les 15 min (tant qu'il n'est pas en veille)."
else
  { crontab -l 2>/dev/null | grep -v "hoka-run-watcher/run.sh" || true; \
    echo "*/15 * * * * /bin/bash $DATA_DIR/run.sh >> $DATA_DIR/watch.log 2>&1"; } | crontab -
  echo "✅ Installé : vérification toutes les 15 min via cron."
fi
echo "   Journal : $DATA_DIR/watch.log"
echo "   Désinstaller : $APP_DIR/install.sh --uninstall"
