"use client";

import React, { useState } from "react";

import {
  requestId,
  STATUS_LABELS,
  type LeadDetail,
  type Status
} from "./lead-detail-model";

type LeadStatusActionProps = {
  apiUrl: string;
  lead: LeadDetail;
  token: string;
  onLeadUpdated: (lead: LeadDetail) => void;
  onUnauthorized: () => void;
};

export function LeadStatusAction({
  apiUrl,
  lead,
  token,
  onLeadUpdated,
  onUnauthorized
}: LeadStatusActionProps) {
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  async function changeStatus() {
    if (pending) {
      return;
    }

    const nextStatus: Status = lead.status === "PENDING" ? "REACHED_OUT" : "PENDING";
    setPending(true);
    setError("");

    try {
      const response = await fetch(`${apiUrl}/api/v1/admin/leads/${lead.id}/status`, {
        method: "PATCH",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
          "X-Request-ID": requestId("status-change")
        },
        body: JSON.stringify({ status: nextStatus, version: lead.version })
      });

      if ([401, 403].includes(response.status)) {
        onUnauthorized();
        return;
      }

      if (response.status === 409) {
        const latestResponse = await fetch(`${apiUrl}/api/v1/admin/leads/${lead.id}`, {
          headers: { Authorization: `Bearer ${token}` }
        });
        if (latestResponse.ok) {
          onLeadUpdated((await latestResponse.json()) as LeadDetail);
          setError(
            "This Lead changed by another Attorney. The latest status is shown; review it and try again."
          );
        } else {
          setError("This Lead changed by another Attorney. Refresh the page and try again.");
        }
        return;
      }

      if (!response.ok) {
        const body = await response.json().catch(() => null);
        setError(body?.detail ?? "The Lead status could not be updated. Please retry.");
        return;
      }

      onLeadUpdated((await response.json()) as LeadDetail);
    } catch {
      setError("The Lead status could not be updated. Please retry.");
    } finally {
      setPending(false);
    }
  }

  return (
    <section className="status-action" aria-label="Current status">
      <p className="eyebrow">Current status</p>
      <span className={`status-pill ${lead.status.toLowerCase()}`}>
        {STATUS_LABELS[lead.status]}
      </span>
      <p>
        {lead.status === "PENDING"
          ? "Record when an Attorney has contacted this Prospect."
          : "Reverse an incorrect update without removing history."}
      </p>
      <button
        className="secondary-button"
        type="button"
        disabled={pending}
        onClick={changeStatus}
      >
        {pending
          ? "Updating..."
          : lead.status === "PENDING"
            ? "Mark reached out"
            : "Return to pending"}
      </button>
      <div className="status-action-message" role="status" aria-live="polite">
        {error ? <p className="field-error">{error}</p> : null}
      </div>
    </section>
  );
}
