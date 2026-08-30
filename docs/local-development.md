# Local development

The local environment uses the Supabase CLI for PostgreSQL, Auth, private
Storage, Studio, and Mailpit. Next.js, FastAPI, and the worker run directly on
the host.

## Setup

```bash
corepack enable
pnpm install
uv sync
pnpm exec supabase start
pnpm exec supabase db reset
pnpm exec supabase status
```

Copy `.env.example` to `.env.local`, then fill these placeholders with the
publishable key from `supabase status`:

- `SUPABASE_ANON_KEY`
- `NEXT_PUBLIC_SUPABASE_ANON_KEY`

## Run

```bash
pnpm dev
```

This root command starts:

- Next.js at `http://localhost:3000`
- FastAPI at `http://127.0.0.1:8000`
- the Python worker on the host process

## Seeded Attorney

Use the seeded account after `pnpm exec supabase db reset`:

- Email: `attorney.local@example.test`
- Password: `LocalAttorney123!`

Public signup is disabled. Create additional Attorney accounts through
Supabase Studio at `http://127.0.0.1:54323`.

## Health

- `GET /health/live` confirms the API process is running.
- `GET /health/ready` confirms required configuration and PostgreSQL
  connectivity.
