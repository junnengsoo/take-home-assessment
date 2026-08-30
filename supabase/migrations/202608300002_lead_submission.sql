create type app.lead_status as enum ('PENDING', 'REACHED_OUT');
create type app.lead_actor_type as enum ('SYSTEM', 'ATTORNEY');

create table app.leads (
  id uuid primary key default extensions.gen_random_uuid(),
  first_name text not null check (length(first_name) between 1 and 120),
  last_name text not null check (length(last_name) between 1 and 120),
  normalized_email extensions.citext not null,
  version integer not null default 1 check (version = 1),
  created_at timestamptz not null default now()
);

create table app.resume_metadata (
  id uuid primary key default extensions.gen_random_uuid(),
  lead_id uuid not null unique references app.leads(id) on delete restrict,
  storage_bucket text not null check (storage_bucket = 'resumes'),
  storage_object_key text not null unique,
  original_filename text not null,
  content_type text not null,
  byte_size integer not null check (byte_size > 0 and byte_size <= 5242880),
  sha256_digest text not null check (sha256_digest ~ '^[0-9a-f]{64}$'),
  created_at timestamptz not null default now()
);

create table app.lead_status_changes (
  id uuid primary key default extensions.gen_random_uuid(),
  lead_id uuid not null references app.leads(id) on delete restrict,
  status app.lead_status not null,
  actor_type app.lead_actor_type not null,
  actor_attorney_id uuid references app.attorneys(id) on delete restrict,
  created_at timestamptz not null default now(),
  check (
    (actor_type = 'SYSTEM' and actor_attorney_id is null)
    or (actor_type = 'ATTORNEY' and actor_attorney_id is not null)
  )
);

create table app.lead_audit_events (
  id uuid primary key default extensions.gen_random_uuid(),
  lead_id uuid not null references app.leads(id) on delete restrict,
  event_type text not null,
  actor_type app.lead_actor_type not null,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table app.submission_attempts (
  id uuid primary key default extensions.gen_random_uuid(),
  attempt_key text not null unique check (length(attempt_key) between 12 and 200),
  request_fingerprint text not null check (request_fingerprint ~ '^[0-9a-f]{64}$'),
  lead_id uuid not null unique references app.leads(id) on delete restrict,
  created_at timestamptz not null default now()
);

create index leads_normalized_email_created_idx
  on app.leads (normalized_email, created_at);

create index lead_status_changes_lead_created_idx
  on app.lead_status_changes (lead_id, created_at);

grant select, insert on app.leads to app_api;
grant select, insert on app.resume_metadata to app_api;
grant select, insert on app.lead_status_changes to app_api;
grant select, insert on app.lead_audit_events to app_api;
grant select, insert on app.submission_attempts to app_api;
