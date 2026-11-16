# Mobile and tablet use

Trading Simulator uses the **same single-asset, portfolio, market-data, and paper-trading features** on desktop and mobile. The responsive layout does not create a separate mobile account or change order execution.

## Open on your phone on the same Wi-Fi

On your Windows PC, update the checkout, then run:

```powershell
git pull
powershell -ExecutionPolicy Bypass -File .\start-local.ps1 -Mobile
```

The launcher keeps the Python API bound to `127.0.0.1:8000` on your PC and starts Vite on port `5173` for access from your trusted private network. Your phone reaches the API through Vite's `/api` proxy. It does **not** need Python, Node.js, or Ollama installed.

The PC console displays an address like `http://192.168.1.123:5173`. On your phone, connect to the same private Wi-Fi and open the exact address shown for your PC. Use **HTTP**, not HTTPS, for this local development server.

If port 5173 was already in use when you added `-Mobile`, stop the previously running **frontend** terminal first, then rerun the launcher with `-Mobile`. A frontend already bound only to loopback cannot automatically switch to LAN mode. The backend can remain running.

If the address does not load:
1. Confirm PC and phone are on the same private network, with no guest-network/client isolation or VPN separation.
2. Check the PC's Wi-Fi IPv4 address using `ipconfig`. Use `http://<PC-IP>:5173`.
3. Allow the Node.js development server through Windows Defender Firewall for **Private** networks if prompted. Do not expose it on Public networks.
4. Keep the PC and both development servers running while using your phone.

The app is a local development tool and has **no authentication** for its paper-account or simulation API. Use `-Mobile` only on trusted private networks. Do not port-forward port 5173, expose it on the public internet, or use an untrusted shared Wi-Fi.

The normal launch without `-Mobile` remains PC-only:

```powershell
powershell -ExecutionPolicy Bypass -File .\start-local.ps1
```

## Touch layout

- Use the two mode buttons at the top to switch between single-asset and portfolio simulations.
- Use the **Workspace sections** selector to open Historical Replay, Market Data & Paper, Orders & Positions, Strategy & AI, Performance Analytics, Scenario Research, or Trade History.
- Charts resize with the phone screen. Touch drag and pinch behavior depends on the underlying lightweight-charts interaction mode.
- Replay steps, order sizing, strategy editing, saved-strategy versions, AI questions, and date controls remain accessible.
- Wider trade history, execution, and analytics tables scroll horizontally within their own panels rather than clipping columns.
- Strategy and order fields have larger touch targets and mobile-safe text sizes.

## Screen sizes to check

Use real devices or responsive browser emulation at widths such as **320, 375, 390, 430, 768, and 1024 px**. Check both portrait and landscape orientations. For each simulation mode, verify switching all workspace sections, viewing charts, entering a strategy, reviewing analytics, and scrolling any wide tables. Mobile layout changes are presentation-only and should preserve simulation and saved data.

This is a responsive web application, not a native iOS or Android app. Local access requires the Windows host to remain online.
