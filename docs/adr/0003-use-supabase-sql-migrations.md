# Use Supabase SQL migrations as the sole schema history

Use versioned Supabase SQL migrations for application tables, Auth profile hooks, private-schema permissions, Storage configuration, and indexes. SQLAlchemy maps the resulting schema but Alembic is not added, avoiding two competing migration histories and ensuring `supabase db reset` recreates the complete local platform deterministically.

