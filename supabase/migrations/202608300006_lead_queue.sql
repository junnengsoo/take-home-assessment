alter table app.leads
  add column if not exists current_status app.lead_status not null default 'PENDING';

create index if not exists leads_queue_created_idx
  on app.leads (created_at desc, id desc);

create index if not exists leads_status_created_idx
  on app.leads (current_status, created_at desc, id desc);

create index if not exists leads_normalized_email_queue_idx
  on app.leads (normalized_email, created_at desc, id desc);
