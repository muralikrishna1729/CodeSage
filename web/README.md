# CodeSage Web

The Next.js App Router frontend and server-side FastAPI proxy for CodeSage.

## Local setup

1. Copy `.env.example` to `.env.local`.
2. Set `CODESAGE_API_KEY` to the local backend API key. Keep it server-side; do not add a `NEXT_PUBLIC_` prefix.
3. Set `CODESAGE_BFF_ENABLED=true` to enable the proxy routes in local development.
4. Set `CODESAGE_ENABLE_INGESTION=true` only when local repository ingestion is intended. It is an independent gate.
5. Start the frontend with `npm run dev`.

The sample environment keeps both access gates disabled. The BFF is disabled by default, and production access should remain disabled until a trusted deployment-level authentication or network boundary is in place.

## Commands

- `npm run dev` — start the development server.
- `npm run typecheck` — run the TypeScript checker.
- `npm run lint` — run ESLint.
- `npm run build` — create a production build.
