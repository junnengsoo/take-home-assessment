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
`pnpm exec supabase status`. Replace `SUPABASE_SERVICE_ROLE_KEY` with the local
service role key from the same status output; it is used only by FastAPI to
write private resume objects. Set `PUBLIC_LEAD_RATE_LIMIT_HMAC_SECRET` to a
local random value. The default Turnstile entries are Cloudflare's official
local/automation test keys. `FALLBACK_INTAKE_ADDRESS` controls the internal
notification recipient used when no Attorney account exists.

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
Attorney profile for each account. All Attorney profiles participate in
round-robin Assignment automatically.

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

Public Lead creation accepts one PDF, DOC, or DOCX resume up to 5 MiB through
FastAPI at `POST /api/v1/leads`. Resume bytes are uploaded to the private
`resumes` Storage bucket with a generated object key, while the original
filename is kept only in private resume metadata.

Each accepted Lead is assigned to the least-recently-assigned Attorney inside
the Lead creation transaction. If no Attorneys exist, the Lead remains
unassigned and the configured Fallback Intake Address receives the internal
notification.

Lead creation also writes two durable `app.notification_outbox` records in the
same transaction: one Prospect confirmation to the submitted email and one
internal notification to the assigned Attorney or fallback address. The
internal payload is limited to Prospect name, email, and submission time;
résumé bytes, object keys, public URLs, filenames, tokens, and secrets are not
queued.

Public Lead creation is protected by a hidden honeypot, a PostgreSQL-backed
request limit keyed by an HMAC of the selected network address, and managed
Cloudflare Turnstile. Explicit Turnstile failures are rejected with retryable
feedback; Cloudflare timeout, network failure, or service outage accepts the
otherwise valid Lead with an internal `UNAVAILABLE` verification outcome.

If resume upload succeeds but database persistence fails, FastAPI attempts to
delete the uploaded object before returning an error. If that compensating
delete also fails, the API logs `resume_compensation_delete_failed` with the
private bucket and generated object key. To clean up such an orphan locally,
open Supabase Studio Storage, select the private `resumes` bucket, verify that
the logged object key has no matching `app.resume_metadata.storage_object_key`,
and delete that object.

## Working agreements

- Keep the solution intentionally small and easy to review.
- Record scope and trade-offs in this README as the work progresses.
- Track planned work and follow-ups in GitHub Issues.
- Prefer a complete, tested core path over broad unfinished functionality.
