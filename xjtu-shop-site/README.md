# xjtu.shop public research site

Public presentation and service-status pages for the DRAM single-event-effects
research project.

## Local development

```powershell
npm ci
npm run dev
```

Build the static site:

```powershell
npm run build
```

Run the status-checker tests:

```powershell
npm run test:status
```

The production static output is written to `dist/`. The status page is built
from the same source and expects a redacted `status.json` next to its deployed
static files.

## Page interactions

The research tabs switch between steps, evidence, and validation. Evidence
cards support mouse, touch, and keyboard selection. Filter chips change the
selected material's overview, record fields, and reproduction note. The
Material dialog holds the extended explanation.

The visual diagrams illustrate research structure. Service badges read the
public status document; data older than three minutes is shown as awaiting
an update. Motion follows `prefers-reduced-motion`. The page uses system
fonts and local SVG icons.

The status dashboard reads the formal month-one case manifest, original run
evidence, and the private Codex progress store. Core, reserve and reusable
controls have separate denominators. Parameter conditions and individual
cases expand on demand and support status filters. Codex records issues,
current actions and next steps through the local CLI.
Tabs support keyboard navigation and refresh every minute.
Task observations have their own timestamp: older observations are labeled as
snapshots and their elapsed time stops at the observation time. Missing
metrics display as unknown. Historical archive counts are separate from
the plan's solver-completion and scientific-acceptance counts.
Recorded time may include waiting and
collection delays and is summed across groups, rather than measured CPU time.

## Public routes

- `www.xjtu.shop` — main research portal (project overview, key highlights, live health badge, and side-by-side entries to `tcad.xjtu.shop` and `status.xjtu.shop`)
- `xjtu.shop` — apex domain permanently redirected (`308`) to `https://www.xjtu.shop`
- `tcad.xjtu.shop` — research presentation homepage (architecture, verified simulation results, interactive SVG charts, and 4-tier evidence boundary)
- `tcad.xjtu.shop/docs/` — technology documentation site (Geant4, Sentaurus TCAD + atomic C++ PMI, `R → A → F` physics-constrained predictor, `server-codex-v2` autonomy, and read-only telemetry stack)
- `status.xjtu.shop` — public resources, simulation observations and service status

All public portals (`www.xjtu.shop`, `tcad.xjtu.shop`, `tcad.xjtu.shop/docs/`, and `status.xjtu.shop`) share Google Material 3 (`@material/web` 2.5.0) light/dark theme tokens, system fonts, local SVG icons with zero external CDN dependencies, and full English/Chinese switching. English (`en`) is the default language; the language choice is shared across `*.xjtu.shop` subdomains via the `xjtu-lang` cookie (`Domain=.xjtu.shop`).

The previous preview route `status.xjtu.shop/research` redirects to `https://tcad.xjtu.shop/`.

`api.xjtu.shop` and `lab.xjtu.shop` remain reserved for
future controlled services.

## Server boundary

The public site is intended to run on the Rocky9 host. It must not proxy
requests into the CentOS7 simulation guest or expose SSH, task paths, run IDs,
license details, or scheduler controls. The status checker only emits the
small public schema used by the status page.

## Data updates

See [ops/PROGRESS-INTERFACE.md](ops/PROGRESS-INTERFACE.md) for the Codex SQLite
interface, and [ops/DATA-SOURCES.md](ops/DATA-SOURCES.md) for case binding,
freshness, privacy and publication behavior. Public HTTP endpoints are read-only.
