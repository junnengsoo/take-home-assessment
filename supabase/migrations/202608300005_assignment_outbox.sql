alter table app.leads
  add column if not exists assigned_attorney_id uuid
    references app.attorneys(id) on delete restrict;

create index if not exists leads_assigned_attorney_created_idx
  on app.leads (assigned_attorney_id, created_at desc, id desc);

create unique index if not exists email_outbox_lead_kind_unique_idx
  on app.email_outbox (lead_id, kind)
  where lead_id is not null;

grant update (last_assigned_at) on app.attorneys to app_api;
