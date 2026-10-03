# Frontend API contract snapshot

`openapi.json` is copied from the accepted local backend contract and is the portable source used by this standalone frontend ZIP.

`src/api/generated/openapi.ts` is generated from this snapshot with:

```text
npm run api:types
```

CI/local validation can detect drift without rewriting files:

```text
npm run api:types:check
```

Browser code never imports Python modules or an external `shared/` runtime folder. When the backend contract changes, refresh this `openapi.json` snapshot first, then regenerate the TypeScript file.
