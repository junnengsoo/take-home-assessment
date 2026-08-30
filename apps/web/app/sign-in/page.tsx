"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

import { createClient } from "../../lib/supabase";

export default function SignInPage() {
  const router = useRouter();
  const [email, setEmail] = useState("attorney.local@example.test");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSubmitting(true);

    const supabase = createClient();
    const { data, error: signInError } = await supabase.auth.signInWithPassword({
      email,
      password
    });

    if (signInError || !data.session?.access_token) {
      setError("Sign in failed. Check the Attorney email and password.");
      setSubmitting(false);
      return;
    }

    const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
    const response = await fetch(`${apiUrl}/api/v1/admin/me`, {
      headers: { Authorization: `Bearer ${data.session.access_token}` }
    });

    if (!response.ok) {
      setError("The API could not verify this Attorney account.");
      setSubmitting(false);
      return;
    }

    router.replace("/workspace");
  }

  return (
    <main className="page">
      <section className="sign-in-shell" aria-label="Attorney sign in">
        <div className="brand-panel">
          <h1>Guided Calm for every Lead.</h1>
          <p>
            Sign in with an administratively managed Attorney account to enter the protected
            workspace. Supabase keeps the session fresh; FastAPI verifies the Attorney identity.
          </p>
        </div>
        <form className="sign-in-card" onSubmit={onSubmit}>
          <h2>Attorney sign in</h2>
          <p>Use the seeded local Attorney account after resetting Supabase.</p>
          {error ? <div className="error">{error}</div> : null}
          <div className="field">
            <label htmlFor="email">Email</label>
            <input
              id="email"
              type="email"
              autoComplete="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
            />
          </div>
          <div className="field">
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
          </div>
          <button className="primary-button" type="submit" disabled={submitting}>
            {submitting ? "Verifying..." : "Sign in"}
          </button>
        </form>
      </section>
    </main>
  );
}
