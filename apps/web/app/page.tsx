"use client";

import { ChangeEvent, FormEvent, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

type FieldErrors = Partial<Record<"firstName" | "lastName" | "email" | "resume", string>>;

function newSubmissionAttemptKey() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export default function Home() {
  const router = useRouter();
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [email, setEmail] = useState("");
  const [resume, setResume] = useState<File | null>(null);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [formError, setFormError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submissionAttemptKey] = useState(newSubmissionAttemptKey);
  const acceptedTypes = useMemo(
    () => ".pdf,.doc,.docx,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    []
  );

  function validate() {
    const nextErrors: FieldErrors = {};
    if (!firstName.trim()) {
      nextErrors.firstName = "Enter your first name.";
    }
    if (!lastName.trim()) {
      nextErrors.lastName = "Enter your last name.";
    }
    if (!email.trim()) {
      nextErrors.email = "Enter your email address.";
    }
    if (!resume) {
      nextErrors.resume = "Upload one PDF, DOC, or DOCX resume.";
    } else if (resume.size > 5 * 1024 * 1024) {
      nextErrors.resume = "Upload a resume that is 5 MiB or smaller.";
    }
    setFieldErrors(nextErrors);
    return Object.keys(nextErrors).length === 0;
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError("");

    if (!validate() || !resume) {
      return;
    }

    setSubmitting(true);
    const data = new FormData();
    data.append("firstName", firstName);
    data.append("lastName", lastName);
    data.append("email", email);
    data.append("submissionAttemptKey", submissionAttemptKey);
    data.append("resume", resume);

    const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
    try {
      const response = await fetch(`${apiUrl}/api/v1/leads`, {
        method: "POST",
        body: data
      });
      const body = await response.json();

      if (!response.ok) {
        setFormError(body.detail ?? "We could not submit your resume. Please try again.");
        setSubmitting(false);
        return;
      }

      router.replace(`/confirmation?leadId=${encodeURIComponent(body.leadId)}`);
    } catch {
      setFormError("The intake service is not reachable. Please try again.");
      setSubmitting(false);
    }
  }

  function onResumeChange(event: ChangeEvent<HTMLInputElement>) {
    setResume(event.target.files?.[0] ?? null);
    setFieldErrors((current) => ({ ...current, resume: undefined }));
  }

  return (
    <main className="intake-page">
      <section className="intake-shell" aria-label="Public lead intake">
        <div className="intake-copy">
          <p className="eyebrow">Guided Calm intake</p>
          <h1>Share your details and resume with care.</h1>
          <p>
            Send one private resume to begin a Lead. The team receives only what they need
            to follow up, and your submission is protected against accidental retries.
          </p>
        </div>
        <form className="intake-form" onSubmit={onSubmit} noValidate>
          <div className="form-heading">
            <h2>Start a Lead</h2>
            <p>All fields are required.</p>
          </div>
          {formError ? (
            <div className="error" role="alert">
              {formError}
            </div>
          ) : null}
          <div className="name-grid">
            <div className="field">
              <label htmlFor="firstName">First name</label>
              <input
                id="firstName"
                name="firstName"
                autoComplete="given-name"
                value={firstName}
                onChange={(event) => setFirstName(event.target.value)}
                aria-invalid={Boolean(fieldErrors.firstName)}
                aria-describedby={fieldErrors.firstName ? "firstName-error" : undefined}
                disabled={submitting}
                required
              />
              {fieldErrors.firstName ? (
                <p className="field-error" id="firstName-error">
                  {fieldErrors.firstName}
                </p>
              ) : null}
            </div>
            <div className="field">
              <label htmlFor="lastName">Last name</label>
              <input
                id="lastName"
                name="lastName"
                autoComplete="family-name"
                value={lastName}
                onChange={(event) => setLastName(event.target.value)}
                aria-invalid={Boolean(fieldErrors.lastName)}
                aria-describedby={fieldErrors.lastName ? "lastName-error" : undefined}
                disabled={submitting}
                required
              />
              {fieldErrors.lastName ? (
                <p className="field-error" id="lastName-error">
                  {fieldErrors.lastName}
                </p>
              ) : null}
            </div>
          </div>
          <div className="field">
            <label htmlFor="email">Email</label>
            <input
              id="email"
              name="email"
              type="email"
              autoComplete="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              aria-invalid={Boolean(fieldErrors.email)}
              aria-describedby={fieldErrors.email ? "email-error" : undefined}
              disabled={submitting}
              required
            />
            {fieldErrors.email ? (
              <p className="field-error" id="email-error">
                {fieldErrors.email}
              </p>
            ) : null}
          </div>
          <div className="field">
            <label htmlFor="resume">Resume</label>
            <input
              id="resume"
              name="resume"
              type="file"
              accept={acceptedTypes}
              onChange={onResumeChange}
              aria-invalid={Boolean(fieldErrors.resume)}
              aria-describedby="resume-help resume-error"
              disabled={submitting}
              required
            />
            <p className="field-help" id="resume-help">
              PDF, DOC, or DOCX up to 5 MiB.
            </p>
            {fieldErrors.resume ? (
              <p className="field-error" id="resume-error">
                {fieldErrors.resume}
              </p>
            ) : null}
          </div>
          <button className="primary-button" type="submit" disabled={submitting}>
            {submitting ? "Submitting..." : "Submit Lead"}
          </button>
        </form>
      </section>
    </main>
  );
}
