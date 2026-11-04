# Mathuq UI

Vanilla HTML/CSS/JS + Vite. No framework.

## Run (dev)

```bash
cd ui
npm install
npm run dev
```

Open http://localhost:5173

The dev server proxies `/api` to the backend.
Default target is `http://localhost:8000`. Override it with:

```bash
API_TARGET=http://backend:8000 npm run dev
```

On Windows PowerShell:

```powershell
$env:API_TARGET="http://backend:8000"; npm run dev
```

## Build

```bash
npm run build
```

## Screens

| Route | Screen |
|---|---|
| `#/`, `#/chat/:id` | Chat: conversation with live streaming and each agent's chain of thought |
| `#/agents` | Agent roster |
| `#/kb` | Knowledge base: documents and a retrieval probe |

## Shared code

- `src/js/api.js`: fetch helper
- `src/js/sse.js`: POST SSE reader
- `src/js/agents.js`: agent colors
- `src/js/router.js`: hash router