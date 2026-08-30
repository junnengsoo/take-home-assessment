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
keys from `supabase status`:

- `SUPABASE_ANON_KEY`
- `NEXT_PUBLIC_SUPABASE_ANON_KEY`
- `SUPABASE_SERVICE_ROLE_KEY`
- `PUBLIC_LEAD_RATE_LIMIT_HMAC_SECRET`

Set `FALLBACK_INTAKE_ADDRESS` to the internal mailbox that should receive new
Lead notifications when no Attorney accounts exist.

The committed defaults use Cloudflare's official Turnstile test site key and
secret key so local development and automation do not depend on a production
Cloudflare widget:

- `NEXT_PUBLIC_TURNSTILE_SITE_KEY=1x00000000000000000000AA`
- `TURNSTILE_SECRET_KEY=1x0000000000000000000000000000000AA`

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
Supabase Studio at `http://127.0.0.1:54323`. Every administratively created
account automatically receives an Attorney profile and participates in
round-robin Assignment.

## Health

- `GET /health/live` confirms the API process is running.
- `GET /health/ready` confirms required configuration and PostgreSQL
  connectivity.

## Lead intake

The public intake form is available at `http://localhost:3000` without signing
in. It posts multipart form data to FastAPI at `POST /api/v1/leads`; the
browser never writes to Supabase Storage or application tables directly.

FastAPI accepts PDF, DOC, and DOCX resumes up to 5 MiB only when the filename
extension, declared MIME type, and file signature agree. It uploads accepted
resume bytes to the private `resumes` bucket using a generated object key and
stores the original filename only as private metadata.

Each form load creates a Submission Attempt key. Retrying the same Submission
Attempt with the same fingerprint returns the existing Lead, while changing
content under the same key returns `409 Conflict`. A later form load creates a
new Submission Attempt and can create a separate Lead even with the same email.

The form executes a managed Cloudflare Turnstile challenge only when the
Prospect submits. The browser sends the resulting token to FastAPI in the same
multipart request as `turnstileToken`; the Turnstile secret is read only from
FastAPI configuration.

FastAPI applies the public request limit before Turnstile verification. The
rate-limit bucket key is an HMAC of the selected network address using
`PUBLIC_LEAD_RATE_LIMIT_HMAC_SECRET`; raw addresses are not stored in the
application table. `X-Forwarded-For` and `X-Real-IP` are used only when the
immediate peer matches `TRUSTED_PROXY_ADDRESSES`, which accepts comma-separated
addresses or CIDR ranges.

Explicit Turnstile validation failures return a retryable problem response and
do not create a Lead. If Cloudflare verification times out, has a network
failure, or returns a service outage, FastAPI accepts the otherwise valid Lead,
stores `UNAVAILABLE` as the internal verification outcome, and logs a sanitized
warning without tokens, names, email addresses, filenames, or raw network
addresses.

For hosted production, create a managed Turnstile widget restricted to the exact
frontend hostnames, set `NEXT_PUBLIC_TURNSTILE_SITE_KEY` to the public site key,
set `TURNSTILE_SECRET_KEY` only in the FastAPI runtime, and set
`TURNSTILE_ALLOWED_HOSTNAMES` to those exact hostnames. Hosted CSP must allow
Turnstile scripts and frames from `https://challenges.cloudflare.com`; the
Next.js app's CSP includes these allowances.

If database persistence fails after Storage upload, the API deletes the uploaded
object. If that compensating delete fails, search the API logs for
`resume_compensation_delete_failed`, then verify the logged object key has no
matching `app.resume_metadata.storage_object_key` before deleting it from the
private `resumes` bucket in Supabase Studio.

Successful Lead creation queues two `app.notification_outbox` rows in the same
database transaction as the Lead, résumé metadata, initial `PENDING` Status
Change, Assignment, creation audit event, and Submission Attempt record. One
row targets the Prospect's submitted email; the internal row targets the
assigned Attorney or fallback address and stores only Prospect name, Prospect
email, and submission time.
