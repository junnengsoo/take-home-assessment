import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const workspace = readFileSync(new URL("../app/workspace/page.tsx", import.meta.url), "utf8");
const detail = readFileSync(
  new URL("../app/workspace/leads/[leadId]/page.tsx", import.meta.url),
  "utf8"
);
const statusAction = readFileSync(
  new URL("../app/workspace/leads/[leadId]/lead-status-action.tsx", import.meta.url),
  "utf8"
);
const styles = readFileSync(new URL("../app/globals.css", import.meta.url), "utf8");

test("queue links each Lead to a dedicated refreshable detail route", () => {
  assert.ok(workspace.includes('href={`/workspace/leads/${lead.id}`}'));
  assert.doesNotMatch(workspace, /setSelectedLead/);
  assert.match(detail, /useParams/);
  assert.match(detail, /leadId/);
  assert.ok(detail.includes("/api/v1/admin/leads/${leadId}"));
});

test("detail page fetches private resume bytes through authenticated FastAPI routes", () => {
  assert.ok(detail.includes("Authorization: `Bearer ${token}`"));
  assert.match(detail, /disposition=inline/);
  assert.match(detail, /disposition=attachment/);
  assert.ok(detail.includes("URL.createObjectURL"));
  assert.ok(detail.includes("URL.revokeObjectURL"));
  assert.match(detail, /resumePreviewUrl/);
  assert.doesNotMatch(detail, /createSignedUrl/);
  assert.equal(detail.includes("storage/v1/object/public"), false);
});

test("detail layout prioritizes prospect information and in-browser resume preview", () => {
  assert.match(detail, /Prospect information/);
  assert.match(detail, /Resume preview/);
  assert.match(detail, /Status history/);
  assert.match(detail, /Download resume/);
  assert.ok(styles.includes(".lead-detail-grid {"));
  assert.ok(styles.includes(".resume-preview-frame {"));
  assert.ok(styles.includes("@media (max-width: 760px)"));
});

test("detail page presents one versioned current-status action and refreshes conflicts", () => {
  assert.match(detail, /LeadStatusAction/);
  assert.match(detail, /onLeadUpdated=\{setLead\}/);
  assert.ok(statusAction.includes("/api/v1/admin/leads/${lead.id}/status"));
  assert.match(statusAction, /method: "PATCH"/);
  assert.ok(statusAction.includes("JSON.stringify({ status: nextStatus, version: lead.version })"));
  assert.match(statusAction, /Mark reached out/);
  assert.match(statusAction, /Return to pending/);
  assert.match(statusAction, /response\.status === 409/);
  assert.match(statusAction, /changed by another Attorney/);
  assert.match(statusAction, /aria-live="polite"/);
  assert.ok(styles.includes(".status-action"));
});
