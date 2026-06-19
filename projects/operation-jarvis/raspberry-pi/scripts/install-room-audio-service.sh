#!/usr/bin/env bash
set -euo pipefail

PI_HOST="${PI_HOST:-}"
PI_USER="${PI_USER:-pi}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/jarvis_dashboard_host}"
SERVER_URL="${SERVER_URL:-}"
POWERCONF_MAC="${POWERCONF_MAC:-}"
CLIENT_REMOTE_PATH="${CLIENT_REMOTE_PATH:-/home/pi/jarvis-room-audio-client.py}"
SERVICE_NAME="${SERVICE_NAME:-jarvis-room-audio.service}"
LOCAL_WAKE_WORD="${LOCAL_WAKE_WORD:-1}"
LOCAL_WAKE_WORD_MODEL="${LOCAL_WAKE_WORD_MODEL:-hey_jarvis}"
LOCAL_WAKE_WORD_THRESHOLD="${LOCAL_WAKE_WORD_THRESHOLD:-0.75}"
LOCAL_WAKE_WORD_NCPU="${LOCAL_WAKE_WORD_NCPU:-2}"
TRUST_LOCAL_WAKE_WORD="${TRUST_LOCAL_WAKE_WORD:-1}"
BT_PLAYBACK_DRAIN_SECONDS="${BT_PLAYBACK_DRAIN_SECONDS:-1.2}"
INSTALL_LOCAL_WAKEWORD_DEPS="${INSTALL_LOCAL_WAKEWORD_DEPS:-1}"
VENV_PATH="${VENV_PATH:-/home/$PI_USER/jarvis-room-audio/.venv}"
PYTHON_BIN="${PYTHON_BIN:-$VENV_PATH/bin/python}"

if [[ -z "$PI_HOST" ]]; then
  echo "Set PI_HOST to the Raspberry Pi hostname or IP." >&2
  exit 2
fi
if [[ -z "$SERVER_URL" ]]; then
  echo "Set SERVER_URL to the room-audio server URL." >&2
  exit 2
fi
if [[ -z "$POWERCONF_MAC" ]]; then
  echo "Set POWERCONF_MAC to the Bluetooth speaker/microphone MAC address." >&2
  exit 2
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
OPERATION_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
CLIENT_LOCAL_PATH="$OPERATION_ROOT/raspberry-pi/room_audio/pi_room_audio_client.py"

if [[ ! -f "$CLIENT_LOCAL_PATH" ]]; then
  echo "Client not found: $CLIENT_LOCAL_PATH" >&2
  exit 1
fi

SSH_OPTS=(-i "$SSH_KEY" -o IdentitiesOnly=yes)
REMOTE="$PI_USER@$PI_HOST"

if [[ "$INSTALL_LOCAL_WAKEWORD_DEPS" != "0" ]]; then
  echo "Installing openWakeWord dependency on $REMOTE in $VENV_PATH"
  ssh "${SSH_OPTS[@]}" "$REMOTE" "set -e; mkdir -p /home/$PI_USER/jarvis-room-audio; sudo apt-get update; sudo apt-get install -y python3-venv python3-numpy python3-scipy python3-sklearn python3-requests python3-tqdm; if [ ! -x '$VENV_PATH/bin/python' ] || ! grep -q '^include-system-site-packages = true' '$VENV_PATH/pyvenv.cfg' 2>/dev/null; then rm -rf '$VENV_PATH'; python3 -m venv --system-site-packages '$VENV_PATH'; fi; '$VENV_PATH/bin/python' -m pip install --upgrade pip setuptools wheel; '$VENV_PATH/bin/python' -m pip install --upgrade tflite-runtime; '$VENV_PATH/bin/python' -m pip install --upgrade --no-deps openwakeword==0.5.1; cat > '$VENV_PATH/lib/python3.11/site-packages/onnxruntime.py' <<'PY'
class SessionOptions:
    def __init__(self):
        self.inter_op_num_threads = 1
        self.intra_op_num_threads = 1

class InferenceSession:
    def __init__(self, *args, **kwargs):
        raise RuntimeError('onnxruntime is not available on this Raspberry Pi; use tflite inference')
PY
'$VENV_PATH/bin/python' -c 'import numpy, scipy, sklearn, tflite_runtime, openwakeword; from openwakeword.model import Model'"
fi

WAKE_ARGS=""
if [[ "$LOCAL_WAKE_WORD" != "0" ]]; then
  WAKE_ARGS="--local-wake-word --openwakeword-model $LOCAL_WAKE_WORD_MODEL --local-wake-word-threshold $LOCAL_WAKE_WORD_THRESHOLD --openwakeword-ncpu $LOCAL_WAKE_WORD_NCPU"
  if [[ "$TRUST_LOCAL_WAKE_WORD" != "0" ]]; then
    WAKE_ARGS="$WAKE_ARGS --trust-local-wake-word"
  fi
fi

# Room audio now treats Pi-side openWakeWord as authoritative. The trust flag is
# still passed for compatibility with older Mac-side servers that supported a
# transcript wake-word re-check.
echo "Copying room-audio client to $REMOTE:$CLIENT_REMOTE_PATH"
scp "${SSH_OPTS[@]}" "$CLIENT_LOCAL_PATH" "$REMOTE:$CLIENT_REMOTE_PATH"

SERVICE_CONTENT=$(cat <<UNIT
[Unit]
Description=Operation JARVIS Raspberry Pi room audio listener
Wants=network-online.target bluetooth.service bluealsa.service
After=network-online.target bluetooth.service bluealsa.service
StartLimitIntervalSec=0

[Service]
Type=simple
User=$PI_USER
WorkingDirectory=/home/$PI_USER
Environment=PYTHONUNBUFFERED=1
ExecStart=$PYTHON_BIN $CLIENT_REMOTE_PATH --server-url $SERVER_URL --device bluealsa:DEV=$POWERCONF_MAC,PROFILE=sco --playback-device bluealsa:DEV=$POWERCONF_MAC,PROFILE=a2dp --rate 8000 --vad-loop --vad-rms-threshold 300 --vad-silence-seconds 1.0 --vad-min-utterance-seconds 0.5 --vad-max-utterance-seconds 30 --vad-preroll-ms 500 --vad-min-voiced-ms 200 --vad-release-capture-during-turn --no-vad-restore-capture-while-waiting $WAKE_ARGS --bt-profile-settle-seconds 0.45 --bt-playback-drain-seconds $BT_PLAYBACK_DRAIN_SECONDS --bluetooth-mac $POWERCONF_MAC --sco-mixer-volume 100 --startup-greeting --no-greeting-on-reconnect --async-ack --poll-interval 0.25 --result-timeout 300 --interval 1.0
Restart=always
RestartSec=5
StandardOutput=append:/home/$PI_USER/jarvis-room-audio/logs/client.log
StandardError=append:/home/$PI_USER/jarvis-room-audio/logs/client.log

[Install]
WantedBy=multi-user.target
UNIT
)

echo "Installing and enabling $SERVICE_NAME on $REMOTE"
printf '%s' "$SERVICE_CONTENT" | ssh "${SSH_OPTS[@]}" "$REMOTE" "cat >/tmp/$SERVICE_NAME && mkdir -p /home/$PI_USER/jarvis-room-audio/logs && chmod +x $CLIENT_REMOTE_PATH && (sudo systemctl stop $SERVICE_NAME 2>/dev/null || true) && (pkill -f 'python3 .*/jarvis-room-audio-client[.]py' 2>/dev/null || true) && sudo mv /tmp/$SERVICE_NAME /etc/systemd/system/$SERVICE_NAME && sudo systemctl daemon-reload && sudo systemctl enable --now $SERVICE_NAME && sudo systemctl restart $SERVICE_NAME && sleep 2 && systemctl --no-pager --full status $SERVICE_NAME | sed -n '1,80p'"

echo "Installed $SERVICE_NAME. Logs: ssh ${SSH_OPTS[*]} $REMOTE 'tail -f /home/$PI_USER/jarvis-room-audio/logs/client.log'"
