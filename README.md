# Take-home assessment

A focused workspace for a software engineering take-home assessment designed to
fit within approximately six hours.

## Local platform

Prerequisites:

- Node.js 22 or newer with Corepack enabled.
- `uv` 0.6.11 or compatible.
- Docker running for the Supabase CLI-managed local services.

Install pinned dependencies:

```bash
corepack enable
pnpm install
uv sync
```

Start or reset Supabase through the pinned CLI package:

```bash
pnpm exec supabase start
pnpm exec supabase db reset
```

Then copy `.env.example` to `.env.local` and replace `SUPABASE_ANON_KEY` and
`NEXT_PUBLIC_SUPABASE_ANON_KEY` with the local publishable key printed by
`pnpm exec supabase status`.

Run Next.js, FastAPI, and the worker directly on the host with one root command:

```bash
pnpm dev
```

Useful local URLs:

- Web: http://localhost:3000
- FastAPI docs: http://127.0.0.1:8000/docs
- Supabase API: http://127.0.0.1:54321
- Supabase Studio: http://127.0.0.1:54323
- Mailpit: http://127.0.0.1:54324

Seeded Attorney login:

- Email: `attorney.local@example.test`
- Password: `LocalAttorney123!`

Supabase Auth public signup is disabled locally. Email/password sign-in stays
enabled so administratively created Attorneys can sign in. Additional Attorney
accounts are created in Supabase Studio; the database trigger creates an
Attorney profile for each account.

## Verification

Run the host-side tests:

```bash
pnpm test
```

After Supabase is started and reset, run the integration tests that exercise the
seeded Supabase sign-in path and protected FastAPI identity lookup:

```bash
pnpm test:local-supabase
```

## Scope notes

FastAPI is the trusted business and security boundary. The browser uses
Supabase Auth only to establish and refresh a session, then sends the Supabase
bearer token to FastAPI for protected application data. Application tables live
in the non-public `app` PostgreSQL schema and are granted only to the local
least-privileged `app_api` role used by FastAPI.

## Working agreements

- Keep the solution intentionally small and easy to review.
- Record scope and trade-offs in this README as the work progresses.
- Track planned work and follow-ups in GitHub Issues.
- Prefer a complete, tested core path over broad unfinished functionality.
