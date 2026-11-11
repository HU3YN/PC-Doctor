# Dashboard

React + TypeScript, built with Vite.

```bash
npm install
npm run dev        # http://localhost:5173 - needs the API on :8000 (python -m pcdoctor_api)
npm run build      # writes dist/, which the API serves by itself
npm test           # unit tests
npm run lint
npm run typecheck
```

| Path | What it is |
|---|---|
| `src/api.ts` | Every API call, with typed responses (mirrors `api/pcdoctor_api/schemas.py`) |
| `src/pages/` | One file per page: runs, run, work log, entry, entry form, look up |
| `src/components/Charts.tsx` | Frame-time and sensor charts (Recharts) |
| `src/components/Bits.tsx` | Badges, notices, the "seen before" case cards |
| `src/styles.css` | All styling; colors are defined once for light and once for dark |

Charts follow a few fixed rules: one y-axis per chart, a part keeps its color
everywhere (CPU first color, GPU second), status is always an icon and a word
rather than color alone, and every charted value is also in the readings table.
