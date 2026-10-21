# Teleop Station UI

The browser UI for the station. It's React 18, TypeScript and Vite. Live plots use uPlot,
and the fonts (Barlow, bundled with the app) work offline.

The UI implements the contract in [`../docs/architecture.md`](../docs/architecture.md):
REST under `/api`, live snapshots on `/ws/state`, logs on `/ws/logs`, and MJPEG camera
previews.

## Run it

```bash
cd ui
npm install
npm run dev          # http://localhost:5173, proxies /api and /ws to the station on :8000
npm run dev:mock     # same, with an in-browser simulation of the whole station (no backend needed)
npm run build        # type-checks, then writes dist/ (served by `station serve` at /)
```

* Point the dev server at a station on another machine with
  `STATION_URL=http://10.0.0.42:8000 npm run dev`.
* Add `?mock=1` to any URL to switch a running UI to mock data, and `?mock=0` to switch back.

## Pages

| Page | What it's for |
|---|---|
| **Operate** | The station state rail (Off → Powered → Arms ready → Teleop → Recording) with the next action next to it, the startup checklist, three camera previews, and a card per arm. Each arm card shows operator squeeze, rendered feedback and follower grip force as a live plot, plus trigger and gripper position, leader vs. follower joints, loop rate, jitter and lag. |
| **Calibrate** | Calibration status by group (leader arms, haptic triggers, gripper force, cameras) and a generic step-by-step wizard driven by the backend's procedure definitions. Includes live readings, a ChArUco overlay for cameras, and standalone script download. |
| **Hardware** | Grouped health checks with fixes, relay channels (toggle and power-cycle), e-stop state, CAN reset, per-arm reconnect, Dynamixel scan, live performance plots and a filterable log console. |
| **Episodes** | Filter, search and select episodes. A detail drawer plays all cameras in sync with a telemetry plot (click to seek) and lets you edit outcome, notes and tags or delete the episode. Multi-select exports to LeRobot, with job progress. |
| **People** | Departments (with colors), tasks and people. There are no passwords. |
| **Settings** | Click-to-bind keyboard shortcuts with conflict detection, handle-button actions, per-arm haptic tuning, and recording options. |

## Keyboard

Shortcuts come from `/api/settings` and use `KeyboardEvent.code`, so foot pedals that
present as keyboards work.

* They're ignored while typing in a field, except e-stop, which always works.
* **Save** opens the save dialog. Pressing Save or Enter again confirms, and **Y**/**N**
  mark the outcome.
* **Abort** asks for confirmation on recordings longer than the configured threshold.
  Pressing it a second time confirms.

## Layout

```
src/
  api/        types.ts (contract types), client.ts (fetch + mock switch), live.ts (WebSocket stores), history.ts (rolling plot buffers)
  mock/       server.ts (simulated station), camera.ts (canvas camera frames)
  state/      appdata.tsx (station, org, settings, session), controller.tsx (actions + shortcuts), toasts.tsx
  components/ Shell, ArmCard, CameraView, Plot, Dialogs, ui primitives, icons
  pages/      Operate, Calibration, Hardware, Episodes, Organization, Settings
  styles/     tokens.css (light/dark tokens), base.css, app.css, pages.css
screenshots/  every page in light and dark at 1440×900
```
