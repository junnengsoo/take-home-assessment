create extension if not exists pgcrypto with schema extensions;
create extension if not exists citext with schema extensions;

do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'app_api') then
    create role app_api login password 'local_app_api_password';
  end if;
end
$$;

create schema if not exists app;

revoke all on schema app from public;
revoke all on schema app from anon;
revoke all on schema app from authenticated;
grant usage on schema app to app_api;

create table if not exists app.attorneys (
  id uuid primary key references auth.users(id) on delete cascade,
  email extensions.citext not null unique,
  display_name text not null,
  last_assigned_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create or replace function app.touch_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists attorneys_touch_updated_at on app.attorneys;
create trigger attorneys_touch_updated_at
before update on app.attorneys
for each row execute function app.touch_updated_at();

create or replace function app.create_attorney_profile()
returns trigger
language plpgsql
security definer
set search_path = app, public, extensions
as $$
declare
  candidate_name text;
begin
  candidate_name := coalesce(
    nullif(new.raw_user_meta_data->>'display_name', ''),
    nullif(split_part(new.email, '@', 1), ''),
    'Attorney'
  );

  insert into app.attorneys (id, email, display_name)
  values (new.id, new.email, candidate_name)
  on conflict (id) do update
    set email = excluded.email,
        display_name = excluded.display_name;

  return new;
end;
$$;

drop trigger if exists create_attorney_profile_after_user_insert on auth.users;
create trigger create_attorney_profile_after_user_insert
after insert on auth.users
for each row execute function app.create_attorney_profile();

grant select on app.attorneys to app_api;

alter default privileges in schema app revoke all on tables from public;

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'resumes',
  'resumes',
  false,
  5242880,
  array[
    'application/pdf',
    'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
  ]
)
on conflict (id) do update
  set public = false,
      file_size_limit = excluded.file_size_limit,
      allowed_mime_types = excluded.allowed_mime_types;
