import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const page = readFileSync(new URL("../app/workspace/page.tsx", import.meta.url), "utf8");
const styles = readFileSync(new URL("../app/globals.css", import.meta.url), "utf8");

test("workspace keeps queue state in the URL and calls protected admin APIs", () => {
  assert.match(page, /useSearchParams/);
  assert.match(page, /router\.replace\(queuePath/);
  assert.match(page, /scope"\) \?\? "my"/);
  assert.match(page, /\/api\/v1\/admin\/attorneys\/me/);
  assert.match(page, /\/api\/v1\/admin\/attorneys/);
  assert.match(page, /\/api\/v1\/admin\/leads\?/);
});

test("workspace exposes desktop queue scopes, filters, and cursor pagination", () => {
  assert.match(page, /My Leads/);
  assert.match(page, /Unassigned/);
  assert.match(page, /All Leads/);
  assert.match(page, /status-filter/);
  assert.match(page, /assignment-filter/);
  assert.match(page, /lead-search/);
  assert.match(page, /nextCursor/);
  assert.match(page, /Next page/);
});

test("workspace has table-first desktop layout and clear queue states", () => {
  assert.match(page, /className="lead-table"/);
  assert.match(page, /Loading Leads/);
  assert.match(page, /No Leads match this view/);
  assert.match(page, /The Lead queue could not be loaded/);
  assert.match(styles, /\.lead-table-wrap\s*\{/);
  assert.match(styles, /\.lead-card-list\s*\{\s*display: none;/);
  assert.match(styles, /@media \(max-width: 760px\)/);
});
