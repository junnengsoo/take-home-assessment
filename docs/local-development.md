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

If database persistence fails after Storage upload, the API deletes the uploaded
object. If that compensating delete fails, search the API logs for
`resume_compensation_delete_failed`, then verify the logged object key has no
matching `app.resume_metadata.storage_object_key` before deleting it from the
private `resumes` bucket in Supabase Studio.
