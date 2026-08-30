import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const workspace = readFileSync(new URL("../app/workspace/page.tsx", import.meta.url), "utf8");
const detail = readFileSync(
  new URL("../app/workspace/leads/[leadId]/page.tsx", import.meta.url),
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
  assert.match(detail, /pdfjs-dist/);
  assert.match(detail, /getDocument/);
  assert.match(detail, /canvas/);
  assert.ok(detail.includes("URL.createObjectURL"));
  assert.ok(detail.includes("URL.revokeObjectURL"));
  assert.match(detail, /resumePreviewReady/);
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
