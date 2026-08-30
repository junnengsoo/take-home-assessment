# Use Supabase for infrastructure primitives

Use Supabase for PostgreSQL, Auth, private object Storage, local email capture, and administrative account provisioning so the local environment and a hosted production environment share the same platform APIs. FastAPI remains the sole business API and authorization boundary; Next.js does not directly manipulate Lead data or resume objects. This accepts Supabase platform coupling in exchange for production-grade primitives and a reproducible environment that fits the assessment's six-hour constraint.

