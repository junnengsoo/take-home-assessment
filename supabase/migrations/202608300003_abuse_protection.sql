do $$
begin
  create type app.turnstile_verification_outcome as enum ('SUCCESS', 'UNAVAILABLE');
exception
  when duplicate_object then null;
end $$;

alter table app.leads
  add column if not exists turnstile_verification_outcome app.turnstile_verification_outcome
    not null default 'SUCCESS';

create table if not exists app.public_lead_rate_limits (
  address_key text primary key check (address_key ~ '^[0-9a-f]{64}$'),
  window_start timestamptz not null,
  request_count integer not null check (request_count > 0),
  updated_at timestamptz not null default now()
);

drop trigger if exists public_lead_rate_limits_touch_updated_at
  on app.public_lead_rate_limits;

create trigger public_lead_rate_limits_touch_updated_at
  before update on app.public_lead_rate_limits
  for each row execute function app.touch_updated_at();

grant select, insert, update on app.public_lead_rate_limits to app_api;
