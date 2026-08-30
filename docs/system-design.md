# System design

This application captures public Prospect submissions as Leads and gives
authenticated Attorneys a focused workspace for follow-up. The implementation is
intentionally production-shaped but small enough for the six-hour assessment:
Supabase provides infrastructure primitives, FastAPI owns business rules and
authorization, Next.js owns the browser experience, and a Python worker delivers
durable email notifications.

## Boundaries

- **Next.js web app** renders the public Lead form, confirmation page, Attorney
  sign-in, Lead queue, Lead detail, private résumé preview/download, and status
  action controls.
- **FastAPI** is the trusted business and security boundary. The browser never
  writes directly to application tables or résumé Storage.
- **Supabase** provides PostgreSQL, Auth, private Storage, Studio, and local
  Mailpit through the Supabase CLI.
- **Worker** reads the PostgreSQL email outbox and sends messages through the
  configured provider.

## Data model

The private `app` schema contains:

- `app.attorneys`: one profile per Supabase Auth user, created by trigger.
- `app.leads`: one distinct Lead per accepted Submission Attempt, including
  normalized email, Assignment, current Lead Status, Turnstile outcome, and
  optimistic-lock version.
- `app.resume_metadata`: private résumé metadata and generated Storage object
  key. Original filenames are retained here, not in logs.
- `app.lead_status_changes`: append-only Status Change history. Reversals append
  a new row instead of deleting previous Attorney work.
- `app.lead_audit_events`: operational audit events with correlation IDs.
- `app.submission_attempts`: idempotency records tying a Submission Attempt key
  to a request fingerprint and Lead.
- `app.email_outbox`: durable notification rows delivered by the worker.
- `app.public_lead_rate_limits`: HMAC-keyed public request-limit buckets.

## Lead submission transaction

`POST /api/v1/leads` validates form fields, résumé type/size/signature, the
honeypot field, request limit, and Turnstile. Explicit Turnstile failures reject
the submission. Turnstile timeouts or service failures accept the otherwise
valid Lead and store `UNAVAILABLE` for internal visibility.

Résumé bytes are uploaded to the private `resumes` bucket under a generated
object key. FastAPI then writes the Lead, résumé metadata, initial `PENDING`
Status Change, creation audit event, Submission Attempt, and two email outbox
records in one PostgreSQL transaction. If database persistence fails after the
Storage upload succeeds, FastAPI attempts a compensating Storage delete.

## Authentication and authorization

Attorneys sign in with Supabase Auth. Next.js uses the Supabase session only to
obtain a bearer token. FastAPI verifies that token against Supabase Auth and
loads the corresponding `app.attorneys` profile before serving protected admin
routes.

Any authenticated Attorney may see Leads and record Status Changes. Assignment
is accountability, not a permission boundary. The default workspace scope is
`My Leads`; Attorneys can also filter by status and assignment or inspect all
Leads.

## Private Storage

Résumés are stored in a private Supabase Storage bucket. The UI previews PDFs by
streaming bytes through authenticated FastAPI and rendering them in-browser. DOC
and DOCX files are download-only. The app does not create public Storage URLs or
long-lived signed URLs.

## Assignment

Lead creation assigns the least-recently-assigned Attorney inside the same
PostgreSQL transaction using a transaction-scoped advisory lock and row lock.
This gives deterministic round-robin behavior without a separate scheduler. If
no Attorney exists, the Lead remains unassigned and the Fallback Intake Address
receives the internal notification.

## Idempotency and concurrency

A Submission Attempt key represents one deliberate form submission. Retrying the
same key with the same request fingerprint returns the existing Lead. Reusing
the key with different content returns `409 Conflict`.

Status updates use the Lead version as an optimistic lock. A stale Attorney tab
receives `409 Conflict`, and the UI refreshes the latest Lead detail rather than
silently overwriting another Attorney's action.

## Abuse controls

The public form uses independent controls:

- hidden honeypot field;
- HMAC-keyed PostgreSQL request limit;
- Cloudflare Turnstile at submission time;
- résumé extension, MIME type, signature, and size validation;
- Submission Attempt idempotency.

Turnstile is a demo anti-abuse integration in local development. Hosted
production should use real Turnstile keys, strict action checks, and exact
frontend hostname checks.

## Email delivery

Lead creation writes one Prospect confirmation and one internal Attorney
notification to `app.email_outbox` in the Lead transaction. The worker claims due
rows with `FOR UPDATE SKIP LOCKED`, sends each message, records provider
metadata on success, and retries temporary failures with exponential backoff.
After five failures, a row moves to `FAILED` and remains inspectable.

Delivery is at-least-once. A duplicate email is possible after an ambiguous
provider acknowledgement, but a committed outbox row should not be silently lost.

## Logging and auditability

FastAPI and the worker emit structured JSON logs with timestamp, severity,
service, environment, event, correlation ID, route template or notification
identity, status, latency, Actor, and Lead where relevant. Automated tests cover
representative redaction so logs do not include bearer tokens, request bodies,
Prospect names or emails, original filenames, résumé content, or raw network
addresses.

Correlation IDs flow from browser/API request headers into API logs, audit
payloads, outbox payloads, and worker delivery logs. This provides traceability
without exposing personal data in log streams.

## Health and failure behavior

- `GET /health/live` reports that the API process is running.
- `GET /health/ready` verifies required configuration and PostgreSQL
  connectivity.

Storage or email degradation does not make the whole API globally unavailable:
those failures are handled on the specific operation path. PostgreSQL
unavailability is readiness-failing because every meaningful application action
depends on it.

## Expected scale

The target assessment scale is approximately 100 Attorneys and 10,000 Leads per
day. The design supports that with indexed queue filters, cursor pagination,
PostgreSQL row locking for outbox workers, small résumé size limits, and simple
round-robin Assignment. For materially higher volume, the next upgrades would be
background malware scanning, more granular queue indexing, managed observability,
and provider-level email event webhooks.

## Hosted-production configuration

A hosted deployment would map the same roles to managed services:

- Next.js hosted on Vercel or an equivalent web runtime.
- FastAPI and the worker as separate long-running services.
- Supabase Cloud project for PostgreSQL, Auth, and private Storage.
- Resend or another production email provider configured only in server-side
  environments.
- Real Turnstile keys with strict action and hostname validation.
- JSON logs shipped to a managed log sink with retention and access controls.

Docker Compose and application Dockerfiles are intentionally out of scope for
this assessment iteration. Local reproducibility is handled by Supabase CLI plus
host-run Next.js, FastAPI, and worker processes.

## Main trade-offs

- Supabase coupling is accepted to get production-grade Auth, PostgreSQL,
  Storage, Studio, and local parity quickly.
- Email outbox is implemented in PostgreSQL instead of introducing a broker.
- Assignment is accountability-focused rather than a restrictive permission
  model, keeping collaboration simple.
- Local seed data uses safe mock DB records for workspace richness; the full
  private résumé byte path is proven by the E2E-submitted Lead.
