# Frontend

React, TypeScript and Vite UI for the Requirements-to-Test Assistant. It sends a requirement to `POST /api/llm/generate` and shows the acceptance criteria, test scenarios with automation recommendations, ambiguities and traceability, with CSV and JSON export.

Requires Node.js 20.19 or newer.

```powershell
npm ci
npm run dev       # http://localhost:5173
npm run lint
npm test
npm run build
```

The backend must be running for generation to work. See the [main README](../README.md) for setup and the frontend settings.

## Structure

| Path | Purpose |
|---|---|
| `src/pages/` | Dashboard, Results, Traceability and NotFound pages |
| `src/components/` | Layout, results, traceability and shared components |
| `src/services/api.ts` | The API call and error messages |
| `src/services/adapter.ts` | Maps the UI text to the request, and the response to the view model |
| `src/context/`, `src/hooks/` | Shared generation state |
| `src/utils/export.ts` | CSV and JSON export |
| `src/data/mockResults.ts` | Sample data, used only when `VITE_USE_MOCK=true` |
