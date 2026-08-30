# Final release checklist

Use this checklist before submitting the public GitHub repository.

## Automated checks

- [ ] Install pinned dependencies with `pnpm install` and `uv sync`.
- [ ] Run host-side checks with `pnpm test`.
- [ ] Start/reset Supabase with `pnpm exec supabase start` and
  `pnpm exec supabase db reset`.
- [ ] Run local Supabase integration checks with `pnpm test:local-supabase`.
- [ ] Run the desktop browser journey with `pnpm test:e2e`.
- [ ] If any check is skipped, record the reason in the submission notes.

## Repository cleanliness

- [ ] `git status --short` shows only intentional tracked changes before the
  final commit.
- [ ] No `.env.local`, downloaded résumés, screenshots, videos, `.next/`,
  Playwright reports, or local Supabase runtime files are staged.
- [ ] PRs/issues referenced by the README and docs use public GitHub links.

## Secret scanning

- [ ] Search for accidental secrets before publishing:

  ```bash
  git grep -nE '(sb_secret_[A-Za-z0-9_-]+|Bearer eyJ[A-Za-z0-9_-]+\.|S3 Secret Key:[[:space:]]*[A-Za-z0-9])' -- ':!.env.example' ':!docs/*'
  git grep -nE '(SUPABASE_SERVICE_ROLE_KEY|RESEND_API_KEY)=([^<].+)' -- ':!.env.example' ':!docs/*'
  ```

- [ ] Confirm `.env.example` contains placeholders only.
- [ ] Confirm docs mention environment variable names, not real local key
  values.
- [ ] Confirm logs/tests do not print bearer tokens, raw request bodies,
  Prospect emails, original résumé filenames, or raw network addresses.

## Safe example configuration

- [ ] `.env.example` contains Cloudflare Turnstile test-key placeholders for
  local/demo use.
- [ ] Local docs explain that `supabase status --output env` provides the
  JWT-style `ANON_KEY` and `SERVICE_ROLE_KEY` expected by this app.
- [ ] Local docs explain that hosted production must use real Turnstile keys
  with strict action and hostname checks.
- [ ] Local docs include seeded Attorney credentials only for safe
  `example.test` demo accounts.

## Public submission readiness

- [ ] The GitHub repository visibility is public.
- [ ] The README provides the shortest path to run, test, understand, and demo
  the app.
- [ ] `docs/system-design.md` explains the architecture and production mapping.
- [ ] `docs/local-development.md` explains setup, Supabase, Mailpit, tests, and
  troubleshooting.
- [ ] The assignment submission includes the GitHub repository link.
