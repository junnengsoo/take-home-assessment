"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { createClient } from "../../../../lib/supabase";
import { requestId, STATUS_LABELS, type LeadDetail } from "./lead-detail-model";
import { LeadStatusAction } from "./lead-status-action";

function formatDate(value: string) {
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit"
  }).format(new Date(value));
}

function formatBytes(value: number) {
  if (value < 1024 * 1024) {
    return `${Math.max(1, Math.round(value / 1024))} KiB`;
  }
  return `${(value / (1024 * 1024)).toFixed(1)} MiB`;
}

function filenameFromDisposition(header: string | null, fallback: string) {
  const match = header?.match(/filename="([^"]+)"/);
  return match?.[1] ?? fallback;
}

export default function LeadDetailPage() {
  const router = useRouter();
  const params = useParams<{ leadId: string }>();
  const leadId = params.leadId;
  const [lead, setLead] = useState<LeadDetail | null>(null);
  const [token, setToken] = useState("");
  const [resumePreviewUrl, setResumePreviewUrl] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [previewError, setPreviewError] = useState("");
  const [downloadError, setDownloadError] = useState("");
  const resumePreviewUrlRef = useRef("");

  const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

  const loadPreview = useCallback(
    async (nextToken: string, nextLead: LeadDetail, isActive: () => boolean) => {
      if (!nextLead.resume.previewable) {
        return;
      }
      const response = await fetch(
        `${apiUrl}/api/v1/admin/leads/${leadId}/resume?disposition=inline`,
        {
          headers: {
            Authorization: `Bearer ${nextToken}`,
            "X-Request-ID": requestId("resume-preview")
          }
        }
      );
      if ([401, 403].includes(response.status)) {
        router.replace("/sign-in");
        return;
      }
      if (!response.ok) {
        if (isActive()) {
          setPreviewError("The résumé preview could not be loaded. Download remains available.");
        }
        return;
      }
      const blob = await response.blob();
      if (!isActive()) {
        return;
      }
      const objectUrl = URL.createObjectURL(blob);
      if (resumePreviewUrlRef.current) {
        URL.revokeObjectURL(resumePreviewUrlRef.current);
      }
      resumePreviewUrlRef.current = objectUrl;
      setResumePreviewUrl(objectUrl);
    },
    [apiUrl, leadId, router]
  );

  useEffect(() => {
    let active = true;

    async function loadLead() {
      setLoading(true);
      setError("");
      setPreviewError("");
      setDownloadError("");

      const supabase = createClient();
      const { data } = await supabase.auth.getSession();
      const nextToken = data.session?.access_token;
      if (!nextToken) {
        router.replace("/sign-in");
        return;
      }

      const response = await fetch(`${apiUrl}/api/v1/admin/leads/${leadId}`, {
        headers: { Authorization: `Bearer ${nextToken}` }
      });

      if ([401, 403].includes(response.status)) {
        router.replace("/sign-in");
        return;
      }
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        if (active) {
          setError(body?.detail ?? "The Lead detail could not be loaded.");
          setLoading(false);
        }
        return;
      }

      const body = (await response.json()) as LeadDetail;
      if (active) {
        setLead(body);
        setToken(nextToken);
        setLoading(false);
        await loadPreview(nextToken, body, () => active);
      }
    }

    loadLead().catch(() => {
      if (active) {
        setError("The Lead detail could not be loaded.");
        setLoading(false);
      }
    });

    return () => {
      active = false;
      if (resumePreviewUrlRef.current) {
        URL.revokeObjectURL(resumePreviewUrlRef.current);
        resumePreviewUrlRef.current = "";
      }
    };
  }, [apiUrl, leadId, loadPreview, router]);

  async function downloadResume() {
    if (!lead || !token) {
      return;
    }
    setDownloadError("");
    const response = await fetch(
      `${apiUrl}/api/v1/admin/leads/${lead.id}/resume?disposition=attachment`,
      {
        headers: {
          Authorization: `Bearer ${token}`,
          "X-Request-ID": requestId("resume-download")
        }
      }
    );
    if ([401, 403].includes(response.status)) {
      router.replace("/sign-in");
      return;
    }
    if (!response.ok) {
      setDownloadError("The résumé could not be downloaded. Please retry.");
      return;
    }
    const blob = await response.blob();
    const objectUrl = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = objectUrl;
    anchor.download = filenameFromDisposition(
      response.headers.get("content-disposition"),
      lead.resume.originalFilename
    );
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(objectUrl);
  }

  if (loading) {
    return (
      <main className="workspace">
        <aside className="rail">
          <h1>Lead Intake</h1>
          <Link className="rail-link" href="/workspace">
            Back to queue
          </Link>
        </aside>
        <section className="workspace-main">
          <div className="queue-state">Loading Lead detail...</div>
        </section>
      </main>
    );
  }

  return (
    <main className="workspace">
      <aside className="rail">
        <h1>Lead Intake</h1>
        <Link className="rail-link" href="/workspace">
          Back to queue
        </Link>
        <div className="rail-attorney">
          <span>Private workspace</span>
          <small>Authenticated résumé access only</small>
        </div>
      </aside>

      <section className="workspace-main">
        {error || !lead ? (
          <div className="queue-state error-state">{error || "Lead not found."}</div>
        ) : (
          <>
            <header className="queue-header">
              <div>
                <p className="eyebrow">Lead Detail</p>
                <h2>
                  {lead.firstName} {lead.lastName}
                </h2>
              </div>
              <span className={`status-pill ${lead.status.toLowerCase()}`}>
                {STATUS_LABELS[lead.status]} · v{lead.version}
              </span>
            </header>

            <div className="lead-detail-grid">
              <section className="detail-panel primary-detail-panel" aria-label="Prospect information">
                <p className="eyebrow">Prospect information</p>
                <dl className="detail-list">
                  <div>
                    <dt>Name</dt>
                    <dd>
                      {lead.firstName} {lead.lastName}
                    </dd>
                  </div>
                  <div>
                    <dt>Email</dt>
                    <dd>{lead.email}</dd>
                  </div>
                  <div>
                    <dt>Submitted</dt>
                    <dd>{formatDate(lead.createdAt)}</dd>
                  </div>
                </dl>

                <div className="resume-preview-card">
                  <div className="resume-preview-heading">
                    <div>
                      <p className="eyebrow">Resume preview</p>
                      <h3>{lead.resume.originalFilename}</h3>
                      <span>
                        {lead.resume.contentType} · {formatBytes(lead.resume.byteSize)}
                      </span>
                    </div>
                    <button className="secondary-button" type="button" onClick={downloadResume}>
                      Download resume
                    </button>
                  </div>

                  {downloadError ? <p className="field-error">{downloadError}</p> : null}

                  {lead.resume.previewable && resumePreviewUrl ? (
                    <iframe
                      className="resume-preview-frame"
                      src={resumePreviewUrl}
                      title="Resume preview"
                    />
                  ) : (
                    <div className="resume-preview-fallback">
                      {previewError ||
                        "This résumé type cannot be previewed safely in the browser. Use download instead."}
                    </div>
                  )}
                </div>
              </section>

              <aside className="detail-panel secondary-detail-panel">
                <LeadStatusAction
                  apiUrl={apiUrl}
                  lead={lead}
                  token={token}
                  onLeadUpdated={setLead}
                  onUnauthorized={() => router.replace("/sign-in")}
                />

                <section aria-label="Assignment">
                  <p className="eyebrow">Assignment</p>
                  <h3>{lead.assignedAttorney?.displayName ?? "Unassigned"}</h3>
                  <p>{lead.assignedAttorney?.email ?? "No Attorney is accountable yet."}</p>
                </section>

                <section aria-label="Status history">
                  <p className="eyebrow">Status history</p>
                  <ol className="status-history">
                    {lead.statusChanges.map((change) => (
                      <li key={change.id}>
                        <span className={`status-pill ${change.status.toLowerCase()}`}>
                          {STATUS_LABELS[change.status]}
                        </span>
                        <strong>
                          {change.actor.type === "SYSTEM"
                            ? "System"
                            : change.actor.attorney.displayName}
                        </strong>
                        <time dateTime={change.createdAt}>{formatDate(change.createdAt)}</time>
                      </li>
                    ))}
                  </ol>
                </section>
              </aside>
            </div>
          </>
        )}
      </section>
    </main>
  );
}
