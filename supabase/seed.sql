insert into auth.users (
  instance_id,
  id,
  aud,
  role,
  email,
  encrypted_password,
  email_confirmed_at,
  raw_app_meta_data,
  raw_user_meta_data,
  created_at,
  updated_at,
  confirmation_token,
  recovery_token,
  email_change_token_new,
  email_change
)
values
  (
    '00000000-0000-0000-0000-000000000000',
    '11111111-1111-4111-8111-111111111111',
    'authenticated',
    'authenticated',
    'attorney.local@example.test',
    crypt('LocalAttorney123!', extensions.gen_salt('bf')),
    now(),
    '{"provider": "email", "providers": ["email"]}'::jsonb,
    '{"display_name": "Local Attorney"}'::jsonb,
    '2026-08-30T08:00:00Z',
    now(),
    '',
    '',
    '',
    ''
  ),
  (
    '00000000-0000-0000-0000-000000000000',
    '22222222-2222-4222-8222-222222222222',
    'authenticated',
    'authenticated',
    'coverage.attorney@example.test',
    crypt('LocalAttorney123!', extensions.gen_salt('bf')),
    now(),
    '{"provider": "email", "providers": ["email"]}'::jsonb,
    '{"display_name": "Coverage Attorney"}'::jsonb,
    '2026-08-30T08:05:00Z',
    now(),
    '',
    '',
    '',
    ''
  ),
  (
    '00000000-0000-0000-0000-000000000000',
    '33333333-3333-4333-8333-333333333333',
    'authenticated',
    'authenticated',
    'intake.partner@example.test',
    crypt('LocalAttorney123!', extensions.gen_salt('bf')),
    now(),
    '{"provider": "email", "providers": ["email"]}'::jsonb,
    '{"display_name": "Intake Partner"}'::jsonb,
    '2026-08-30T08:10:00Z',
    now(),
    '',
    '',
    '',
    ''
  )
on conflict (id) do update
  set email = excluded.email,
      encrypted_password = excluded.encrypted_password,
      email_confirmed_at = excluded.email_confirmed_at,
      raw_app_meta_data = excluded.raw_app_meta_data,
      raw_user_meta_data = excluded.raw_user_meta_data,
      updated_at = now();

insert into auth.identities (
  id,
  user_id,
  provider_id,
  identity_data,
  provider,
  last_sign_in_at,
  created_at,
  updated_at
)
values
  (
    'aaaaaaaa-0000-4000-8000-000000000001',
    '11111111-1111-4111-8111-111111111111',
    '11111111-1111-4111-8111-111111111111',
    '{"sub": "11111111-1111-4111-8111-111111111111", "email": "attorney.local@example.test"}'::jsonb,
    'email',
    now(),
    now(),
    now()
  ),
  (
    'aaaaaaaa-0000-4000-8000-000000000002',
    '22222222-2222-4222-8222-222222222222',
    '22222222-2222-4222-8222-222222222222',
    '{"sub": "22222222-2222-4222-8222-222222222222", "email": "coverage.attorney@example.test"}'::jsonb,
    'email',
    now(),
    now(),
    now()
  ),
  (
    'aaaaaaaa-0000-4000-8000-000000000003',
    '33333333-3333-4333-8333-333333333333',
    '33333333-3333-4333-8333-333333333333',
    '{"sub": "33333333-3333-4333-8333-333333333333", "email": "intake.partner@example.test"}'::jsonb,
    'email',
    now(),
    now(),
    now()
  )
on conflict (provider, provider_id) do update
  set identity_data = excluded.identity_data,
      updated_at = now();

insert into app.attorneys (id, email, display_name, last_assigned_at, created_at)
values
  (
    '11111111-1111-4111-8111-111111111111',
    'attorney.local@example.test',
    'Local Attorney',
    '2026-08-30T08:00:00Z',
    '2026-08-30T08:00:00Z'
  ),
  (
    '22222222-2222-4222-8222-222222222222',
    'coverage.attorney@example.test',
    'Coverage Attorney',
    '2026-08-30T08:20:00Z',
    '2026-08-30T08:05:00Z'
  ),
  (
    '33333333-3333-4333-8333-333333333333',
    'intake.partner@example.test',
    'Intake Partner',
    '2026-08-30T08:40:00Z',
    '2026-08-30T08:10:00Z'
  )
on conflict (id) do update
  set email = excluded.email,
      display_name = excluded.display_name,
      last_assigned_at = excluded.last_assigned_at,
      updated_at = now();

insert into app.leads (
  id,
  first_name,
  last_name,
  normalized_email,
  version,
  created_at,
  turnstile_verification_outcome,
  assigned_attorney_id,
  current_status
)
values
  (
    '44444444-4444-4444-8444-444444444441',
    'Avery',
    'Rivera',
    'avery.rivera@example.test',
    1,
    '2026-08-30T09:00:00Z',
    'SUCCESS',
    '11111111-1111-4111-8111-111111111111',
    'PENDING'
  ),
  (
    '44444444-4444-4444-8444-444444444442',
    'Blake',
    'Chen',
    'blake.chen@example.test',
    2,
    '2026-08-30T09:15:00Z',
    'SUCCESS',
    '22222222-2222-4222-8222-222222222222',
    'REACHED_OUT'
  ),
  (
    '44444444-4444-4444-8444-444444444443',
    'Casey',
    'Morgan',
    'casey.morgan@example.test',
    3,
    '2026-08-30T09:30:00Z',
    'UNAVAILABLE',
    '11111111-1111-4111-8111-111111111111',
    'PENDING'
  )
on conflict (id) do update
  set first_name = excluded.first_name,
      last_name = excluded.last_name,
      normalized_email = excluded.normalized_email,
      version = excluded.version,
      turnstile_verification_outcome = excluded.turnstile_verification_outcome,
      assigned_attorney_id = excluded.assigned_attorney_id,
      current_status = excluded.current_status;

insert into app.resume_metadata (
  id,
  lead_id,
  storage_bucket,
  storage_object_key,
  original_filename,
  content_type,
  byte_size,
  sha256_digest,
  created_at
)
values
  (
    '55555555-5555-4555-8555-555555555551',
    '44444444-4444-4444-8444-444444444441',
    'resumes',
    'demo/avery-rivera.pdf',
    'avery-rivera-resume.pdf',
    'application/pdf',
    1024,
    repeat('a', 64),
    '2026-08-30T09:00:05Z'
  ),
  (
    '55555555-5555-4555-8555-555555555552',
    '44444444-4444-4444-8444-444444444442',
    'resumes',
    'demo/blake-chen.pdf',
    'blake-chen-resume.pdf',
    'application/pdf',
    2048,
    repeat('b', 64),
    '2026-08-30T09:15:05Z'
  ),
  (
    '55555555-5555-4555-8555-555555555553',
    '44444444-4444-4444-8444-444444444443',
    'resumes',
    'demo/casey-morgan.docx',
    'casey-morgan-resume.docx',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    3072,
    repeat('c', 64),
    '2026-08-30T09:30:05Z'
  )
on conflict (lead_id) do update
  set storage_bucket = excluded.storage_bucket,
      storage_object_key = excluded.storage_object_key,
      original_filename = excluded.original_filename,
      content_type = excluded.content_type,
      byte_size = excluded.byte_size,
      sha256_digest = excluded.sha256_digest;

insert into app.lead_status_changes (
  id,
  lead_id,
  status,
  actor_type,
  actor_attorney_id,
  created_at
)
values
  (
    '66666666-6666-4666-8666-666666666661',
    '44444444-4444-4444-8444-444444444441',
    'PENDING',
    'SYSTEM',
    null,
    '2026-08-30T09:00:10Z'
  ),
  (
    '66666666-6666-4666-8666-666666666662',
    '44444444-4444-4444-8444-444444444442',
    'PENDING',
    'SYSTEM',
    null,
    '2026-08-30T09:15:10Z'
  ),
  (
    '66666666-6666-4666-8666-666666666663',
    '44444444-4444-4444-8444-444444444442',
    'REACHED_OUT',
    'ATTORNEY',
    '22222222-2222-4222-8222-222222222222',
    '2026-08-30T09:45:00Z'
  ),
  (
    '66666666-6666-4666-8666-666666666664',
    '44444444-4444-4444-8444-444444444443',
    'PENDING',
    'SYSTEM',
    null,
    '2026-08-30T09:30:10Z'
  ),
  (
    '66666666-6666-4666-8666-666666666665',
    '44444444-4444-4444-8444-444444444443',
    'REACHED_OUT',
    'ATTORNEY',
    '11111111-1111-4111-8111-111111111111',
    '2026-08-30T10:00:00Z'
  ),
  (
    '66666666-6666-4666-8666-666666666666',
    '44444444-4444-4444-8444-444444444443',
    'PENDING',
    'ATTORNEY',
    '11111111-1111-4111-8111-111111111111',
    '2026-08-30T10:15:00Z'
  )
on conflict (id) do nothing;

insert into app.lead_audit_events (
  id,
  lead_id,
  event_type,
  actor_type,
  payload,
  created_at
)
values
  (
    '77777777-7777-4777-8777-777777777771',
    '44444444-4444-4444-8444-444444444441',
    'lead.created',
    'SYSTEM',
    '{"correlationId": "seed-avery-created"}'::jsonb,
    '2026-08-30T09:00:10Z'
  ),
  (
    '77777777-7777-4777-8777-777777777772',
    '44444444-4444-4444-8444-444444444442',
    'lead.created',
    'SYSTEM',
    '{"correlationId": "seed-blake-created"}'::jsonb,
    '2026-08-30T09:15:10Z'
  ),
  (
    '77777777-7777-4777-8777-777777777773',
    '44444444-4444-4444-8444-444444444442',
    'lead.status_changed',
    'ATTORNEY',
    '{"correlationId": "seed-blake-reached-out", "fromStatus": "PENDING", "toStatus": "REACHED_OUT"}'::jsonb,
    '2026-08-30T09:45:00Z'
  ),
  (
    '77777777-7777-4777-8777-777777777774',
    '44444444-4444-4444-8444-444444444443',
    'lead.created',
    'SYSTEM',
    '{"correlationId": "seed-casey-created"}'::jsonb,
    '2026-08-30T09:30:10Z'
  ),
  (
    '77777777-7777-4777-8777-777777777775',
    '44444444-4444-4444-8444-444444444443',
    'lead.status_changed',
    'ATTORNEY',
    '{"correlationId": "seed-casey-reached-out", "fromStatus": "PENDING", "toStatus": "REACHED_OUT"}'::jsonb,
    '2026-08-30T10:00:00Z'
  ),
  (
    '77777777-7777-4777-8777-777777777776',
    '44444444-4444-4444-8444-444444444443',
    'lead.status_changed',
    'ATTORNEY',
    '{"correlationId": "seed-casey-reversed", "fromStatus": "REACHED_OUT", "toStatus": "PENDING"}'::jsonb,
    '2026-08-30T10:15:00Z'
  )
on conflict (id) do nothing;
