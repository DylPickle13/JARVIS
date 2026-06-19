# Operation JARVIS Smart Plugs

Local control for TP-Link Kasa HS103 smart plugs used around the house by Operation JARVIS.

**Local/private operations note:** this README intentionally contains local plug names, LAN IPs, and credential-loading paths. Keep it private; do not publish without review.

**Appliance safety:** avoid unattended automation for heating or high-risk devices. In particular, treat `kettle` as a manual/supervised control target only unless a separate physical safety interlock/runbook exists.

Current configured plugs:

```text
<configured-plug-name> -> <private-lan-ip>    label: configured room light, verified locally controllable
kettle -> <private-lan-ip>          label: Kettle, verified locally controllable
lamp -> <private-lan-ip>             label: Lamp, verified locally controllable
tv -> <private-lan-ip>              label: TV, verified locally controllable
```

## Preferred JARVIS control

For Pi/local-model tool use, load the JARVIS tool group and use the dedicated `smart_plug` tool. The normal schema is intentionally small: `action` is required, and `plug` is only needed for `status`, `on`, `off`, or `toggle`.

Before turning on a plug attached to an appliance, confirm the attached device is safe to energize and supervised.

```json
{ "action": "list" }
{ "action": "status", "plug": "<configured-plug-name>" }
{ "action": "on", "plug": "<configured-plug-name>" }
{ "action": "off", "plug": "<configured-plug-name>" }
{ "action": "toggle", "plug": "tv" }
```

From the Operation JARVIS root:

```bash
cd /path/to/JARVIS/projects/operation-jarvis

./jarvis-cli plug-list
./jarvis-cli plug-status <configured-plug-name>
./jarvis-cli plug-on <configured-plug-name>
./jarvis-cli plug-off <configured-plug-name>
./jarvis-cli plug-toggle tv
```

Machine-readable output:

```bash
./jarvis-cli --json plug-status kettle
```

## Direct low-level control

Use this when testing the plug subsystem directly:

```bash
cd /path/to/JARVIS/projects/operation-jarvis/smart-plug
source .venv/bin/activate

plugctl list
plugctl status <configured-plug-name>
plugctl on <configured-plug-name>
plugctl off <configured-plug-name>
plugctl toggle tv
```

If `plugctl` is not on `PATH`, use the module directly:

```bash
python -m smart_plug.cli status <configured-plug-name>
```

## Credentials

The HS103 hardware v5 units require TP-Link/Kasa credentials for local IOT KLAP v2 control.

Credentials are loaded in this order:

1. `projects/operation-jarvis/smart-plug/.env`
2. `projects/operation-jarvis/.env`
3. repo-root `.env`

Example:

```env
KASA_USERNAME=your_tp_link_email@example.com
KASA_PASSWORD=your_tp_link_kasa_password
```

Do **not** commit `.env`.

If the Kasa app was originally using Google/Apple/social login, set a real TP-Link ID/Kasa password first, then use that password here.

Third-Party Compatibility must remain enabled in the Kasa/Tapo app for local third-party control. TP-Link disables this by default on newer firmware; when it was disabled, the plugs were discoverable but rejected local KLAP authentication.

If plugs were genuinely onboarded before and after a TP-Link password change, their device-local KLAP credentials may differ. Add extra passwords locally; JARVIS will try them in order:

```env
KASA_USERNAME=your_tp_link_email@example.com
KASA_PASSWORD=primary_password
KASA_PASSWORD_2=alternate_password
```

## Setup from scratch

The main Operation JARVIS virtualenv may use Python 3.9 for older voice/Cast dependencies. This smart-plug subsystem intentionally has its own Python 3.11+ virtualenv because HS103 hardware v5 needs a newer `python-kasa` KLAP v2 auth path.

```bash
cd /path/to/JARVIS/projects/operation-jarvis/smart-plug
/opt/homebrew/bin/python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt -e .
plugctl --help
```

This project installs a `python-kasa` PR build because the normal PyPI build failed against HS103 hardware v5 / IOT KLAP v2 authentication.

## Add another HS103 plug

1. Add the plug in the Kasa app on the same 2.4 GHz Wi-Fi network.
2. Give it a clear alias, e.g. `Lamp`.
3. Find its IP address in the router, Kasa app/device info, or with discovery from a machine on the LAN.
4. Add it to `plugs.json`:

```json
{
  "plugs": {
    "<configured-plug-name>": {"host": "<private-lan-ip>"},
    "kettle": {"host": "<private-lan-ip>"},
    "lamp": {"host": "<private-lan-ip>"},
    "tv": {"host": "<private-lan-ip>"}
  }
}
```

5. Test it:

```bash
./jarvis-cli plug-status lamp
./jarvis-cli plug-on lamp
./jarvis-cli plug-off lamp
```

## Discovery

Discovery may not work from the VM because broadcast traffic can be blocked by NAT. Direct IP control works once a plug is in `plugs.json`.

From Operation JARVIS:

```bash
./jarvis-cli plug-discover
./jarvis-cli plug-save-discovery
```

Or direct:

```bash
KASA_DISCOVERY_TARGET=<private-lan-ip> plugctl discover
```

## Troubleshooting

### `Device response did not match our challenge`

The plug was found, but authentication failed. Check:

- `KASA_USERNAME` is the exact TP-Link/Kasa account email.
- `KASA_PASSWORD` is the TP-Link/Kasa password, not merely a Google/Apple social-login password.
- If credentials are correct and the plug reports `ANS=True` in local discovery, enable **Third-Party Compatibility** in the Kasa/Tapo app: **Me → Third-Party Services → Third-Party Compatibility**. In Kasa app versions, this may be **Me → Settings → Third-Party Compatibility**.
- If only some plugs fail after a real password change, add the other TP-Link password as `KASA_PASSWORD_2` in a local `.env`; plugs onboarded before/after a password change can keep different local credentials.
- The installed dependency is the PR build from `requirements.txt`.

Reinstall if needed:

```bash
cd /path/to/JARVIS/projects/operation-jarvis/smart-plug
source .venv/bin/activate
pip install --force-reinstall -r requirements.txt -e .
```

### No device discovered

Use the known IP in `plugs.json`, or find the plug IP in the router/Kasa app. Broadcast discovery is optional.
