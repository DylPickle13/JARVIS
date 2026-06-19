# Troubleshooting LAN access

## Confirm the dashboard is running

On the host running Operation JARVIS:

```bash
cd /path/to/JARVIS/projects/operation-jarvis/dashboard
curl http://127.0.0.1:8787/api/status
npm run url
```

Open one of the printed LAN URLs from the phone. Prefer the dashboard host real home-network IP, for example:

```text
http://<dashboard-host>:8787
```

Do not use a VM/NAT-only address such as `<vm-nat-ip>` from the phone.

## Reinstall the LaunchAgent

```bash
cd /path/to/JARVIS/projects/operation-jarvis/dashboard
npm run install-service
```

Check logs:

```text
projects/operation-jarvis/dashboard/logs/launchd.out.log
projects/operation-jarvis/dashboard/logs/launchd.err.log
```

## macOS firewall

If localhost works but the phone cannot connect:

1. Open **System Settings → Network → Firewall**.
2. Open **Options**.
3. Allow incoming connections for Node.js / the terminal runtime.
4. Try the LAN URL again.

## Port already in use

Run on another port temporarily:

```bash
cd /path/to/JARVIS/projects/operation-jarvis/dashboard
PORT=8788 npm start
```

Then browse to `http://MAC_MINI_LAN_IP:8788`.
