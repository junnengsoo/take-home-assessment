import assert from "node:assert/strict";
import { afterEach, before, test } from "node:test";

import { JSDOM } from "jsdom";
import React, { useState } from "react";

import type { LeadDetail, Status } from "../app/workspace/leads/[leadId]/lead-detail-model";

const dom = new JSDOM("<!doctype html><html><body></body></html>", {
  url: "http://localhost"
});
Object.defineProperties(globalThis, {
  window: { value: dom.window, configurable: true, writable: true },
  document: { value: dom.window.document, configurable: true, writable: true },
  navigator: { value: dom.window.navigator, configurable: true, writable: true },
  HTMLElement: { value: dom.window.HTMLElement, configurable: true, writable: true },
  Node: { value: dom.window.Node, configurable: true, writable: true },
  MutationObserver: { value: dom.window.MutationObserver, configurable: true, writable: true },
  getComputedStyle: { value: dom.window.getComputedStyle, configurable: true, writable: true },
  IS_REACT_ACT_ENVIRONMENT: { value: true, configurable: true, writable: true }
});

let cleanup: typeof import("@testing-library/react").cleanup;
let fireEvent: typeof import("@testing-library/react").fireEvent;
let render: typeof import("@testing-library/react").render;
let screen: typeof import("@testing-library/react").screen;
let LeadStatusAction: typeof import(
  "../app/workspace/leads/[leadId]/lead-status-action"
).LeadStatusAction;

before(async () => {
  ({ cleanup, fireEvent, render, screen } = await import("@testing-library/react"));
  ({ LeadStatusAction } = await import(
    "../app/workspace/leads/[leadId]/lead-status-action"
  ));
});

function statusChange(status: Status, id: string): LeadDetail["statusChanges"][number] {
  return {
    id,
    status,
    actor: { type: "SYSTEM" },
    createdAt: "2026-08-30T14:00:00+00:00"
  };
}

const initialLead: LeadDetail = {
  id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  firstName: "Ada",
  lastName: "Lovelace",
  email: "ada@example.com",
  status: "PENDING",
  version: 1,
  createdAt: "2026-08-30T14:00:00+00:00",
  assignedAttorney: null,
  resume: {
    id: "33333333-3333-4333-8333-333333333333",
    originalFilename: "Ada Resume.pdf",
    contentType: "application/pdf",
    byteSize: 18,
    createdAt: "2026-08-30T14:00:00+00:00",
    previewable: true
  },
  statusChanges: [statusChange("PENDING", "44444444-4444-4444-8444-444444444444")]
};

function Harness({ initial = initialLead }: { initial?: LeadDetail }) {
  const [lead, setLead] = useState(initial);
  return (
    <>
      <LeadStatusAction
        apiUrl="http://api.test"
        lead={lead}
        token="attorney-token"
        onLeadUpdated={setLead}
        onUnauthorized={() => undefined}
      />
      <output aria-label="Rendered history">
        {lead.statusChanges.map((change) => change.status).join(" → ")}
      </output>
    </>
  );
}

function jsonResponse(body: object, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" }
  });
}

afterEach(() => {
  cleanup();
});

test("Attorney can perform both status transitions and render appended history", async () => {
  const requests: Array<[RequestInfo | URL, RequestInit | undefined]> = [];
  const responses = [
    jsonResponse({
      ...initialLead,
      status: "REACHED_OUT",
      version: 2,
      statusChanges: [
        ...initialLead.statusChanges,
        statusChange("REACHED_OUT", "55555555-5555-4555-8555-555555555555")
      ]
    }),
    jsonResponse({
      ...initialLead,
      status: "PENDING",
      version: 3,
      statusChanges: [
        ...initialLead.statusChanges,
        statusChange("REACHED_OUT", "55555555-5555-4555-8555-555555555555"),
        statusChange("PENDING", "66666666-6666-4666-8666-666666666666")
      ]
    })
  ];
  globalThis.fetch = async (input, init) => {
    requests.push([input, init]);
    const response = responses.shift();
    assert.ok(response);
    return response;
  };

  render(<Harness />);
  fireEvent.click(screen.getByRole("button", { name: "Mark reached out" }));

  await screen.findByRole("button", { name: "Return to pending" });
  assert.equal(screen.getByLabelText("Rendered history").textContent, "PENDING → REACHED_OUT");
  assert.deepEqual(JSON.parse(String(requests[0][1]?.body)), {
    status: "REACHED_OUT",
    version: 1
  });

  fireEvent.click(screen.getByRole("button", { name: "Return to pending" }));

  await screen.findByRole("button", { name: "Mark reached out" });
  assert.equal(
    screen.getByLabelText("Rendered history").textContent,
    "PENDING → REACHED_OUT → PENDING"
  );
  assert.deepEqual(JSON.parse(String(requests[1][1]?.body)), {
    status: "PENDING",
    version: 2
  });
});

test("stale status mutation visibly reloads the latest Lead", async () => {
  const latestLead: LeadDetail = {
    ...initialLead,
    status: "REACHED_OUT",
    version: 2,
    statusChanges: [
      ...initialLead.statusChanges,
      statusChange("REACHED_OUT", "55555555-5555-4555-8555-555555555555")
    ]
  };
  const requests: Array<[RequestInfo | URL, RequestInit | undefined]> = [];
  const responses = [
    jsonResponse({ code: "lead_version_conflict" }, 409),
    jsonResponse(latestLead)
  ];
  globalThis.fetch = async (input, init) => {
    requests.push([input, init]);
    const response = responses.shift();
    assert.ok(response);
    return response;
  };

  render(<Harness />);
  fireEvent.click(screen.getByRole("button", { name: "Mark reached out" }));

  await screen.findByText(/changed by another Attorney/);
  assert.equal(screen.getByRole("button").textContent, "Return to pending");
  assert.equal(screen.getByLabelText("Rendered history").textContent, "PENDING → REACHED_OUT");
  assert.equal(requests[1][1]?.method, undefined);
  assert.equal(String(requests[1][0]), `${requests[0][0]}`.replace("/status", ""));
});
