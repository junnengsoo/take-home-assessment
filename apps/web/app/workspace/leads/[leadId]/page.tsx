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
  const [resumePreviewReady, setResumePreviewReady] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [previewError, setPreviewError] = useState("");
  const [downloadError, setDownloadError] = useState("");
  const resumePreviewContainerRef = useRef<HTMLDivElement | null>(null);

  const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

  const loadPreview = useCallback(
    async (nextToken: string, nextLead: LeadDetail, isActive: () => boolean) => {
      if (!nextLead.resume.previewable) {
        return;
      }
      setResumePreviewReady(false);
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
      const arrayBuffer = await response.arrayBuffer();
      if (!isActive()) {
        return;
      }

      const container = resumePreviewContainerRef.current;
      if (!container) {
        if (isActive()) {
          setPreviewError("The résumé preview could not be prepared. Download remains available.");
        }
        return;
      }

      try {
        const pdfjs = await import("pdfjs-dist");
        pdfjs.GlobalWorkerOptions.workerSrc = new URL(
          "pdfjs-dist/build/pdf.worker.mjs",
          import.meta.url
        ).toString();

        const loadingTask = pdfjs.getDocument({ data: new Uint8Array(arrayBuffer) });
        const pdf = await loadingTask.promise;
        const availableWidth = Math.max(320, container.clientWidth || 720) - 32;
        const pixelRatio = window.devicePixelRatio || 1;

        container.replaceChildren();

        for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber += 1) {
          const page = await pdf.getPage(pageNumber);
          const unscaledViewport = page.getViewport({ scale: 1 });
          const scale = Math.min(1.6, Math.max(0.8, availableWidth / unscaledViewport.width));
          const viewport = page.getViewport({ scale });
          const canvas = document.createElement("canvas");
          const context = canvas.getContext("2d");
          if (!context) {
            throw new Error("canvas_context_unavailable");
          }

          canvas.width = Math.floor(viewport.width * pixelRatio);
          canvas.height = Math.floor(viewport.height * pixelRatio);
          canvas.style.width = `${Math.floor(viewport.width)}px`;
          canvas.style.height = `${Math.floor(viewport.height)}px`;
          canvas.setAttribute("aria-label", `Resume preview page ${pageNumber}`);

          context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
          context.clearRect(0, 0, viewport.width, viewport.height);
          await page.render({ canvasContext: context, viewport }).promise;
          container.append(canvas);
        }
        await pdf.destroy();

        if (isActive()) {
          setResumePreviewReady(true);
        }
      } catch {
        resumePreviewContainerRef.current?.replaceChildren();
        if (isActive()) {
          setPreviewError("The résumé preview could not be rendered. Download remains available.");
        }
      }
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
      setResumePreviewReady(false);

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
    };
  }, [apiUrl, leadId, router]);

  useEffect(() => {
    if (!lead || !token) {
      return;
    }
    let active = true;
    loadPreview(token, lead, () => active).catch(() => {
      if (active) {
        setPreviewError("The résumé preview could not be rendered. Download remains available.");
      }
    });
    return () => {
      active = false;
    };
  }, [lead, loadPreview, token]);

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

                  {lead.resume.previewable ? (
                    <div className="resume-preview-frame">
                      {!resumePreviewReady && !previewError ? (
                        <div className="resume-preview-loading">Rendering secure preview...</div>
                      ) : null}
                      {previewError ? (
                        <div className="resume-preview-fallback">{previewError}</div>
                      ) : (
                        <div
                          ref={resumePreviewContainerRef}
                          className="resume-preview-pages"
                          aria-label="Resume preview pages"
                        />
                      )}
                    </div>
                  ) : (
                    <div className="resume-preview-fallback">
                      This résumé type cannot be previewed safely in the browser. Use download
                      instead.
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
