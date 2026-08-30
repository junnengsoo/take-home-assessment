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

`pnpm exec supabase status` prints the local URLs used throughout the demo:

- API URL: `http://127.0.0.1:54321`
- Database URL: `postgresql://postgres:postgres@127.0.0.1:54322/postgres`
- Studio URL: `http://127.0.0.1:54323`
- Mailpit URL: `http://127.0.0.1:54324`
- S3 Storage URL: `http://127.0.0.1:54321/storage/v1/s3`

Recent Supabase CLI versions also print `Publishable key` and `Secret key`
values in this normal status output. Those `sb_...` values are not the values
to paste into the current application env names. This app currently expects
the JWT-style local keys from:

```bash
pnpm exec supabase status --output env
```

Copy `.env.example` to `.env.local`, then fill these placeholders with the
`--output env` values:

- `SUPABASE_ANON_KEY`
- `NEXT_PUBLIC_SUPABASE_ANON_KEY`
- `SUPABASE_SERVICE_ROLE_KEY`
- `PUBLIC_LEAD_RATE_LIMIT_HMAC_SECRET`

Use `ANON_KEY` for both anon settings and `SERVICE_ROLE_KEY` for the server-only
Storage setting.

Set `FALLBACK_INTAKE_ADDRESS` to the internal mailbox that should receive new
Lead notifications when no Attorney accounts exist.

The committed defaults use Cloudflare's official Turnstile test site key and
secret key so local development and automation do not depend on a production
Cloudflare widget:

- `NEXT_PUBLIC_TURNSTILE_SITE_KEY=1x00000000000000000000AA`
- `TURNSTILE_SECRET_KEY=1x0000000000000000000000000000000AA`

For local manual smoke testing, Siteverify may return a static dummy success
payload with no action and `example.com` as the hostname. If that happens, set
these local `.env.local` values for the demo:

- `TURNSTILE_EXPECTED_ACTION=`
- `TURNSTILE_ALLOWED_HOSTNAMES=example.com`

Those relaxed action and hostname settings are only for the local dummy-key
demo. Hosted production must use real Turnstile keys, keep an expected action
such as `lead_submit`, and restrict allowed hostnames to the exact frontend
domains.

## Run

```bash
pnpm dev
```

This root command starts:

- Next.js at `http://localhost:3000`
- FastAPI at `http://127.0.0.1:8000`
- the Python email worker on the host process

## Seeded demo data

Use the primary seeded account after `pnpm exec supabase db reset`:

- Email: `attorney.local@example.test`
- Password: `LocalAttorney123!`

The reset also creates safe mock Attorney accounts and representative Leads
with `PENDING`, `REACHED_OUT`, and reversed history states. These records use
`example.test` addresses and synthetic résumé metadata so the workspace has
meaningful queue data immediately. SQL seed data does not upload real local
Storage bytes for those synthetic résumé objects; the private résumé byte path
is exercised by submitting a fresh Lead through the public form or by running
the desktop E2E journey.

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

Successful Lead creation queues two `app.email_outbox` rows in the same
database transaction as the Lead, résumé metadata, initial `PENDING` Status
Change, Assignment, creation audit event, and Submission Attempt record. One
row targets the Prospect's submitted email; the internal row targets the
assigned Attorney or fallback address and stores only Prospect name, Prospect
email, and submission time.

## Email delivery

`pnpm dev` runs the lightweight Python email worker alongside Next.js and
FastAPI. The worker claims due `app.email_outbox` rows directly from PostgreSQL
using row locking, sends the message, and records the provider identifier,
delivery timestamp, and attempt count on success.

Local delivery uses Supabase CLI's Mailpit SMTP service by default:

- SMTP: `127.0.0.1:54325`
- Web inbox: `http://127.0.0.1:54324`

Temporary failures are retained on the outbox row with sanitized error context
and retried with exponential delay. After five failed attempts, the row moves to
`FAILED` and remains inspectable in PostgreSQL instead of being discarded.

Delivery is intentionally at-least-once. If the provider accepts a message but
the worker crashes before PostgreSQL records success, a later worker may send
that notification again. This rare duplicate is acceptable for the assessment;
silent loss is not.

The committed production-facing provider interface also supports Resend from
the server-only worker process. Hosted production should set:

- `EMAIL_PROVIDER=resend`
- `RESEND_API_KEY=<server-only-resend-api-key>`
- `EMAIL_FROM_ADDRESS=<verified-sender>`

Do not expose `RESEND_API_KEY` to Next.js or any browser-facing environment.
Outbox notification templates intentionally omit résumé attachments, Storage
object keys, bearer tokens, and public download links. Internal notifications
tell Attorneys to open the authenticated workspace to review the private
résumé.

Lead creation should enqueue one `PROSPECT_CONFIRMATION` row addressed to the
Prospect and one `INTERNAL_NEW_LEAD` row addressed to the assigned Attorney, or
to the Fallback Intake Address when no Assignment exists. The worker consumes
the queued recipient and template payload; it does not perform Assignment or
recipient selection itself.

## Observability

FastAPI and the worker emit structured JSON application logs. Each log record
includes timestamp, severity, service, environment, event, and correlation
identity, plus operation-specific fields such as route template, HTTP status,
latency, Actor, Lead, notification kind, and provider.

The app deliberately does not log bearer tokens, request bodies, Prospect names
or emails, original résumé filenames, résumé content, or raw network addresses.
Representative redaction behavior is covered by automated tests.

## Test commands

Run the host-side unit/source checks:

```bash
pnpm test
```

After Supabase is started and reset, run the local Supabase integration checks:

```bash
pnpm test:local-supabase
```

Run the desktop Playwright journey:

```bash
pnpm test:e2e
```

The Playwright journey assumes Supabase has been started/reset and `.env.local`
contains the current JWT-style local keys from `pnpm exec supabase status
--output env`. It reuses an existing `pnpm dev` server if one is already
running; otherwise Playwright starts the root dev command.

## Common troubleshooting

- **Port 8000 already in use**: stop the other FastAPI/dev process, then rerun
  `pnpm dev`.
- **`turnstile_verification_failed` locally**: when using Cloudflare test keys,
  set `TURNSTILE_EXPECTED_ACTION=` and `TURNSTILE_ALLOWED_HOSTNAMES=example.com`
  in `.env.local`, then restart `pnpm dev`.
- **`resume_upload_failed` locally**: confirm `.env.local` uses `ANON_KEY` and
  `SERVICE_ROLE_KEY` from `pnpm exec supabase status --output env`, not the
  newer `sb_publishable_...` / `sb_secret_...` values from normal status output.
- **No email in Mailpit**: confirm the worker is running through `pnpm dev`,
  `EMAIL_PROVIDER=local-smtp`, `EMAIL_SMTP_HOST=127.0.0.1`, and
  `EMAIL_SMTP_PORT=54325`.
- **Readiness fails**: `GET /health/ready` depends on required configuration
  and PostgreSQL connectivity. Storage or email issues are surfaced only on the
  specific operation that needs them.
