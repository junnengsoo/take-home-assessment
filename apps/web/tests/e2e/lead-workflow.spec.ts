import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { writeFileSync } from "node:fs";

const ATTORNEY_PASSWORD = "LocalAttorney123!";
const MAILPIT_URL = process.env.MAILPIT_URL ?? "http://127.0.0.1:54324";
const SEEDED_ATTORNEY_EMAILS = [
  "attorney.local@example.test",
  "coverage.attorney@example.test",
  "intake.partner@example.test"
];

test("desktop Lead workflow from public submission to reversed outreach", async ({
  page,
  request
}, testInfo) => {
  testInfo.setTimeout(90_000);
  await stubTurnstile(page);

  const runId = Date.now();
  const prospect = {
    firstName: "E2E",
    lastName: `Prospect ${runId}`,
    email: `e2e.prospect.${runId}@example.test`
  };
  const resumePath = testInfo.outputPath("resume.pdf");
  writeFileSync(resumePath, demoPdfBytes(`Lead ${runId}`));

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Share your details and resume with care." })).toBeVisible();
  await page.getByLabel("First name").fill(prospect.firstName);
  await page.getByLabel("Last name").fill(prospect.lastName);
  await page.getByLabel("Email").fill(prospect.email);
  await page.getByLabel("Resume").setInputFiles(resumePath);
  await page.getByRole("button", { name: "Submit Lead" }).click();

  await expect(page.getByRole("heading", { name: "Thank you. Your resume has been received." })).toBeVisible();
  const leadId = new URL(page.url()).searchParams.get("leadId");
  expect(leadId).toMatch(/^[0-9a-f-]{36}$/);

  await expectMessage(request, (message) =>
    message.includes("We received your Lead") && message.includes(prospect.email)
  );
  await expectMessage(request, (message) =>
    message.includes("New Lead:") && message.includes(`${prospect.firstName} ${prospect.lastName}`)
  );

  await signInAndOpenAssignedMyLead(page, prospect);

  await expect(page.getByRole("heading", { name: `${prospect.firstName} ${prospect.lastName}` })).toBeVisible();
  await expect(page.getByText(prospect.email)).toBeVisible();
  await expect(page.getByLabel("Resume preview pages")).toBeVisible();
  await expect(page.locator('canvas[aria-label="Resume preview page 1"]')).toBeVisible();

  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download resume" }).click();
  await expect((await download).suggestedFilename()).toMatch(/\.pdf$/);

  await page.getByRole("button", { name: "Mark reached out" }).click();
  await expect(page.getByText("Reached out · v2")).toBeVisible();
  await expect(page.getByText("Reverse an incorrect update without removing history.")).toBeVisible();
  await expect(page.getByLabel("Status history").getByText("Reached out")).toBeVisible();

  await page.getByRole("button", { name: "Return to pending" }).click();
  await expect(page.getByText("Pending · v3")).toBeVisible();
  await expect(page.getByText("Record when an Attorney has contacted this Prospect.")).toBeVisible();
  await expect(page.getByLabel("Status history").getByText("Pending")).toHaveCount(2);

  await page.reload();
  await expect(page.getByText("Pending · v3")).toBeVisible();
  await expect(page.getByText(prospect.email)).toBeVisible();
});

async function signInAndOpenAssignedMyLead(
  page: Page,
  prospect: { firstName: string; lastName: string; email: string }
) {
  for (const attorneyEmail of SEEDED_ATTORNEY_EMAILS) {
    await page.goto("/sign-in");
    await page.getByLabel("Email").fill(attorneyEmail);
    await page.getByLabel("Password").fill(ATTORNEY_PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();

    const signInFailed = await page
      .getByText("Sign in failed. Check the Attorney email and password.")
      .isVisible({ timeout: 1_000 })
      .catch(() => false);
    if (signInFailed) {
      continue;
    }

    await expect(page.getByRole("heading", { name: "My Leads" })).toBeVisible();
    await page.getByLabel("Email").fill(prospect.email);
    await page.getByRole("button", { name: "Search" }).click();

    const link = page.getByRole("link", {
      name: new RegExp(`${prospect.firstName} ${prospect.lastName}`)
    });
    if ((await link.count()) > 0) {
      await expect(link).toBeVisible();
      await link.click();
      return;
    }
  }
  throw new Error("submitted Lead was not visible in any seeded Attorney's My Leads queue");
}

async function stubTurnstile(page: Page) {
  await page.route(
    "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit",
    async (route) => {
      await route.fulfill({
        contentType: "application/javascript",
        body: `
        window.turnstile = {
          render: (_element, options) => {
            window.__leadIntakeTurnstileOptions = options;
            return "local-demo-widget";
          },
          execute: () => {
            window.__leadIntakeTurnstileOptions.callback("local-demo-turnstile-token");
          },
          reset: () => {},
          remove: () => {}
        };
      `
      });
    }
  );
}

function demoPdfBytes(label: string) {
  const escapedLabel = label.replace(/[()\\]/g, "");
  const content = `BT /F1 18 Tf 72 140 Td (${escapedLabel}) Tj ET`;
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 360 240] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
    `<< /Length ${Buffer.byteLength(content)} >>\nstream\n${content}\nendstream`,
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
  ];
  const offsets: number[] = [];
  let pdf = "%PDF-1.4\n";
  for (const [index, object] of objects.entries()) {
    offsets.push(Buffer.byteLength(pdf));
    pdf += `${index + 1} 0 obj\n${object}\nendobj\n`;
  }
  const xrefOffset = Buffer.byteLength(pdf);
  pdf += `xref\n0 ${objects.length + 1}\n`;
  pdf += "0000000000 65535 f \n";
  for (const offset of offsets) {
    pdf += `${String(offset).padStart(10, "0")} 00000 n \n`;
  }
  pdf += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\n`;
  pdf += `startxref\n${xrefOffset}\n%%EOF\n`;
  return Buffer.from(pdf);
}

async function expectMessage(
  request: APIRequestContext,
  predicate: (message: string) => boolean
) {
  await expect
    .poll(async () => {
      const response = await request.get(`${MAILPIT_URL}/api/v1/messages`);
      if (!response.ok()) {
        return false;
      }
      const body = await response.json();
      const messages = body.messages ?? body.Messages ?? [];
      return messages.some((message: unknown) => predicate(JSON.stringify(message)));
    })
    .toBe(true);
}
