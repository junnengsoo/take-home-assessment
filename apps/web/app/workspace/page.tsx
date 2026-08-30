"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, Suspense, useEffect, useMemo, useState } from "react";

import { createClient } from "../../lib/supabase";

type Attorney = {
  id: string;
  email: string;
  displayName: string;
};

type QueueLead = {
  id: string;
  firstName: string;
  lastName: string;
  email: string;
  status: "PENDING" | "REACHED_OUT";
  version: number;
  createdAt: string;
  assignedAttorney: Attorney | null;
};

type QueueResponse = {
  leads: QueueLead[];
  counts: {
    my: number;
    unassigned: number;
    all: number;
  };
  nextCursor: string | null;
};

const SCOPES = [
  { key: "my", label: "My Leads", count: "my" },
  { key: "unassigned", label: "Unassigned", count: "unassigned" },
  { key: "all", label: "All Leads", count: "all" }
] as const;

const STATUS_LABELS = {
  PENDING: "Pending",
  REACHED_OUT: "Reached out"
};

function queuePath(params: URLSearchParams) {
  const query = params.toString();
  return query ? `/workspace?${query}` : "/workspace";
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit"
  }).format(new Date(value));
}

export default function WorkspacePage() {
  return (
    <Suspense fallback={<WorkspaceLoading />}>
      <WorkspaceQueue />
    </Suspense>
  );
}

function WorkspaceLoading() {
  return (
    <main className="workspace">
      <aside className="rail">
        <h1>Lead Intake</h1>
      </aside>
      <section className="workspace-main">
        <div className="queue-state">Loading workspace...</div>
      </section>
    </main>
  );
}

function WorkspaceQueue() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const scope = searchParams.get("scope") ?? "my";
  const status = searchParams.get("status") ?? "";
  const assignment = searchParams.get("assignment") ?? "";
  const q = searchParams.get("q") ?? "";
  const cursor = searchParams.get("cursor") ?? "";
  const [attorney, setAttorney] = useState<Attorney | null>(null);
  const [attorneys, setAttorneys] = useState<Attorney[]>([]);
  const [queue, setQueue] = useState<QueueResponse | null>(null);
  const [searchInput, setSearchInput] = useState(q);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const activeScope = SCOPES.some((item) => item.key === scope) ? scope : "my";

  useEffect(() => {
    setSearchInput(q);
  }, [q]);

  const apiQuery = useMemo(() => {
    const params = new URLSearchParams();
    params.set("scope", activeScope);
    if (status) {
      params.set("status", status);
    }
    if (assignment) {
      params.set("assignment", assignment);
    }
    if (q) {
      params.set("q", q);
    }
    if (cursor) {
      params.set("cursor", cursor);
    }
    return params;
  }, [activeScope, assignment, cursor, q, status]);

  function nextParams(changes: Record<string, string | null>, resetCursor = true) {
    const params = new URLSearchParams(searchParams.toString());
    for (const [key, value] of Object.entries(changes)) {
      if (!value) {
        params.delete(key);
      } else {
        params.set(key, value);
      }
    }
    if (resetCursor) {
      params.delete("cursor");
    }
    if (params.get("scope") === "my") {
      params.delete("scope");
    }
    return params;
  }

  function replaceState(changes: Record<string, string | null>, resetCursor = true) {
    router.replace(queuePath(nextParams(changes, resetCursor)));
  }

  useEffect(() => {
    let active = true;

    async function loadQueue() {
      setLoading(true);
      setError("");

      const supabase = createClient();
      const { data } = await supabase.auth.getSession();
      const token = data.session?.access_token;
      if (!token) {
        router.replace("/sign-in");
        return;
      }

      const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
      const headers = { Authorization: `Bearer ${token}` };
      const [meResponse, attorneysResponse, queueResponse] = await Promise.all([
        fetch(`${apiUrl}/api/v1/admin/attorneys/me`, { headers }),
        fetch(`${apiUrl}/api/v1/admin/attorneys`, { headers }),
        fetch(`${apiUrl}/api/v1/admin/leads?${apiQuery.toString()}`, { headers })
      ]);

      const authFailed = [meResponse, attorneysResponse, queueResponse].some((response) =>
        [401, 403].includes(response.status)
      );

      if (authFailed) {
        router.replace("/sign-in");
        return;
      }

      if (!meResponse.ok || !attorneysResponse.ok || !queueResponse.ok) {
        const body = await queueResponse.json().catch(() => null);
        if (active) {
          setError(body?.detail ?? "The Lead queue could not be loaded.");
          setLoading(false);
        }
        return;
      }

      const [meBody, attorneysBody, queueBody] = await Promise.all([
        meResponse.json(),
        attorneysResponse.json(),
        queueResponse.json()
      ]);

      if (active) {
        setAttorney(meBody);
        setAttorneys(attorneysBody);
        setQueue(queueBody);
        setLoading(false);
      }
    }

    loadQueue().catch(() => {
      if (active) {
        setError("The Lead queue could not be loaded.");
        setLoading(false);
      }
    });

    return () => {
      active = false;
    };
  }, [apiQuery, router]);

  function onSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    replaceState({ q: searchInput.trim() || null });
  }

  const counts = queue?.counts ?? { my: 0, unassigned: 0, all: 0 };
  const currentScope = SCOPES.find((item) => item.key === activeScope) ?? SCOPES[0];

  return (
    <main className="workspace">
      <aside className="rail">
        <h1>Lead Intake</h1>
        <nav aria-label="Workspace">
          {SCOPES.map((item) => {
            const params = nextParams({ scope: item.key });
            const active = item.key === activeScope;
            return (
              <Link
                key={item.key}
                aria-current={active ? "page" : undefined}
                className={active ? "rail-link active" : "rail-link"}
                href={queuePath(params)}
              >
                <span>{item.label}</span>
                <span>{counts[item.count]}</span>
              </Link>
            );
          })}
        </nav>
        <div className="rail-attorney">
          <span>{attorney?.displayName ?? "Attorney"}</span>
          <small>{attorney?.email ?? "Verifying session"}</small>
        </div>
      </aside>

      <section className="workspace-main">
        <header className="queue-header">
          <div>
            <p className="eyebrow">Attorney workspace</p>
            <h2>{currentScope.label}</h2>
          </div>
          <div className="metric-row" aria-label="Lead counts">
            <div>
              <span>{counts.my}</span>
              <small>Mine</small>
            </div>
            <div>
              <span>{counts.unassigned}</span>
              <small>Unassigned</small>
            </div>
            <div>
              <span>{counts.all}</span>
              <small>All</small>
            </div>
          </div>
        </header>

        <form className="queue-controls" onSubmit={onSearch}>
          <div className="compact-field search-field">
            <label htmlFor="lead-search">Email</label>
            <input
              id="lead-search"
              type="search"
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
              placeholder="prospect@example.com"
            />
          </div>
          <div className="compact-field">
            <label htmlFor="status-filter">Status</label>
            <select
              id="status-filter"
              value={status}
              onChange={(event) => replaceState({ status: event.target.value || null })}
            >
              <option value="">Any</option>
              <option value="PENDING">Pending</option>
              <option value="REACHED_OUT">Reached out</option>
            </select>
          </div>
          <div className="compact-field">
            <label htmlFor="assignment-filter">Assignment</label>
            <select
              id="assignment-filter"
              value={assignment}
              onChange={(event) => replaceState({ assignment: event.target.value || null })}
            >
              <option value="">Any</option>
              <option value="me">Me</option>
              <option value="unassigned">Unassigned</option>
              {attorneys.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.displayName}
                </option>
              ))}
            </select>
          </div>
          <button className="secondary-button" type="submit">
            Search
          </button>
        </form>

        {loading ? <div className="queue-state">Loading Leads...</div> : null}
        {error ? <div className="queue-state error-state">{error}</div> : null}
        {!loading && !error && queue?.leads.length === 0 ? (
          <div className="queue-state">No Leads match this view.</div>
        ) : null}

        {!loading && !error && queue && queue.leads.length > 0 ? (
          <>
            <div className="lead-table-wrap">
              <table className="lead-table">
                <thead>
                  <tr>
                    <th>Prospect</th>
                    <th>Status</th>
                    <th>Assignment</th>
                    <th>Submitted</th>
                  </tr>
                </thead>
                <tbody>
                  {queue.leads.map((lead) => (
                    <tr key={lead.id}>
                      <td>
                        <strong>
                          {lead.firstName} {lead.lastName}
                        </strong>
                        <span>{lead.email}</span>
                      </td>
                      <td>
                        <span className={`status-pill ${lead.status.toLowerCase()}`}>
                          {STATUS_LABELS[lead.status]}
                        </span>
                      </td>
                      <td>{lead.assignedAttorney?.displayName ?? "Unassigned"}</td>
                      <td>{formatDate(lead.createdAt)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="lead-card-list" aria-label="Lead cards">
              {queue.leads.map((lead) => (
                <article className="lead-card" key={lead.id}>
                  <div>
                    <strong>
                      {lead.firstName} {lead.lastName}
                    </strong>
                    <span>{lead.email}</span>
                  </div>
                  <span className={`status-pill ${lead.status.toLowerCase()}`}>
                    {STATUS_LABELS[lead.status]}
                  </span>
                  <dl>
                    <div>
                      <dt>Assignment</dt>
                      <dd>{lead.assignedAttorney?.displayName ?? "Unassigned"}</dd>
                    </div>
                    <div>
                      <dt>Submitted</dt>
                      <dd>{formatDate(lead.createdAt)}</dd>
                    </div>
                  </dl>
                </article>
              ))}
            </div>

            <div className="pagination-row">
              <span>{cursor ? "Continuing from cursor" : "Newest first"}</span>
              <button
                className="secondary-button"
                type="button"
                disabled={!queue.nextCursor}
                onClick={() => replaceState({ cursor: queue.nextCursor }, false)}
              >
                Next page
              </button>
            </div>
          </>
        ) : null}
      </section>
    </main>
  );
}
