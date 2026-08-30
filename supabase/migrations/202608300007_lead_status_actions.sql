alter table app.leads
  drop constraint if exists leads_version_check;

alter table app.leads
  add constraint leads_version_positive_check check (version > 0);

grant update (current_status, version) on app.leads to app_api;
