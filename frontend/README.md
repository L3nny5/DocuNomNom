# DocuNomNom Frontend

Phase 0 scaffold of the React + TypeScript + Vite UI.

## Layout

```
src/
  app/             Routing / shell (Phase 0: minimal placeholder page)
  features/
    jobs/          Phase 3
    history/       Phase 3
    config/        Phase 3
    review/        Phase 4 (visual PDF review)
  components/ui/   shadcn-style primitives (Phase 3)
  i18n/            react-i18next setup (Phase 3); locales already stubbed
  api/             Generated OpenAPI client (Phase 3)
  lib/             Shared hooks/utilities (Phase 3+)
tests/
  unit/            Vitest + React Testing Library (Phase 3+)
  e2e/             Playwright smoke (Phase 4)
```

## Scripts

- `npm run dev` — start the Vite dev server.
- `npm run build` — type check then build.
- `npm run typecheck` — strict TypeScript.
- `npm run format` / `npm run format:fix` — Prettier.

ESLint, Tailwind, shadcn/ui, TanStack Query, react-pdf, and react-i18next are
deliberately not yet installed in Phase 0 to keep the scaffold minimal. They
are added in the phase that first needs them.
