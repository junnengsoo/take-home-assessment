"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { createClient } from "../../lib/supabase";

type Attorney = {
  id: string;
  email: string;
  displayName: string;
};

export default function WorkspacePage() {
  const router = useRouter();
  const [attorney, setAttorney] = useState<Attorney | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;

    async function load() {
      const supabase = createClient();
      const { data } = await supabase.auth.getSession();
      const token = data.session?.access_token;
      if (!token) {
        router.replace("/sign-in");
        return;
      }

      const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
      const response = await fetch(`${apiUrl}/api/v1/attorneys/me`, {
        headers: { Authorization: `Bearer ${token}` }
      });

      if (!response.ok) {
        router.replace("/sign-in");
        return;
      }

      if (active) {
        setAttorney(await response.json());
        setLoading(false);
      }
    }

    load();
    return () => {
      active = false;
    };
  }, [router]);

  return (
    <main className="workspace">
      <aside className="rail">
        <h1>Lead Intake</h1>
        <nav aria-label="Workspace">
          <Link href="/workspace">My Leads</Link>
          <Link href="/workspace">Unassigned</Link>
          <Link href="/workspace">All Leads</Link>
        </nav>
      </aside>
      <section className="workspace-main">
        <h2>My Leads</h2>
        <p>The protected workspace shell is ready for the Lead queue.</p>
        <div className="summary-card">
          {loading ? (
            <p>Verifying Attorney session...</p>
          ) : (
            <>
              <h3>Signed in</h3>
              <p>
                {attorney?.displayName} is verified by FastAPI as {attorney?.email}.
              </p>
            </>
          )}
        </div>
      </section>
    </main>
  );
}
