do $$
begin
  create type app.email_notification_kind as enum (
    'PROSPECT_CONFIRMATION',
    'INTERNAL_NEW_LEAD'
  );
exception
  when duplicate_object then null;
end $$;

do $$
begin
  create type app.email_outbox_status as enum ('PENDING', 'SENT', 'FAILED');
exception
  when duplicate_object then null;
end $$;

create table if not exists app.email_outbox (
  id uuid primary key default extensions.gen_random_uuid(),
  lead_id uuid references app.leads(id) on delete restrict,
  kind app.email_notification_kind not null,
  recipient_email extensions.citext not null,
  payload jsonb not null default '{}'::jsonb,
  status app.email_outbox_status not null default 'PENDING',
  attempt_count integer not null default 0 check (attempt_count >= 0 and attempt_count <= 5),
  next_attempt_at timestamptz not null default now(),
  claimed_at timestamptz,
  claim_token uuid,
  provider_name text,
  provider_message_id text,
  delivered_at timestamptz,
  last_error_context jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (
    (status = 'SENT' and delivered_at is not null and provider_name is not null and provider_message_id is not null)
    or (status <> 'SENT' and delivered_at is null)
  ),
  check (
    status <> 'FAILED'
    or (attempt_count = 5 and last_error_context <> '{}'::jsonb)
  )
);

drop trigger if exists email_outbox_touch_updated_at on app.email_outbox;
create trigger email_outbox_touch_updated_at
before update on app.email_outbox
for each row execute function app.touch_updated_at();

create index if not exists email_outbox_available_idx
  on app.email_outbox (status, next_attempt_at, created_at, id)
  where status = 'PENDING';

create index if not exists email_outbox_lead_created_idx
  on app.email_outbox (lead_id, created_at);

grant select, insert, update on app.email_outbox to app_api;
