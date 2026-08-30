do $$
begin
  create type app.notification_type as enum (
    'PROSPECT_CONFIRMATION',
    'INTERNAL_LEAD_CREATED'
  );
exception
  when duplicate_object then null;
end $$;

alter table app.leads
  add column if not exists assigned_attorney_id uuid
    references app.attorneys(id) on delete restrict;

create table if not exists app.notification_outbox (
  id uuid primary key default extensions.gen_random_uuid(),
  lead_id uuid not null references app.leads(id) on delete restrict,
  notification_type app.notification_type not null,
  recipient_email extensions.citext not null,
  recipient_attorney_id uuid references app.attorneys(id) on delete restrict,
  payload jsonb not null default '{}'::jsonb,
  status text not null default 'PENDING' check (status = 'PENDING'),
  created_at timestamptz not null default now(),
  check (
    (notification_type = 'PROSPECT_CONFIRMATION' and recipient_attorney_id is null)
    or notification_type = 'INTERNAL_LEAD_CREATED'
  ),
  unique (lead_id, notification_type)
);

create index if not exists leads_assigned_attorney_created_idx
  on app.leads (assigned_attorney_id, created_at desc, id desc);

create index if not exists notification_outbox_pending_created_idx
  on app.notification_outbox (status, created_at, id);

grant update (last_assigned_at) on app.attorneys to app_api;
grant select, insert on app.notification_outbox to app_api;
