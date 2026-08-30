import Link from "next/link";

export default async function ConfirmationPage({
  searchParams
}: {
  searchParams: Promise<{ leadId?: string }>;
}) {
  const { leadId } = await searchParams;

  return (
    <main className="confirmation-page">
      <section className="confirmation-shell" aria-label="Lead confirmation">
        <p className="eyebrow">Lead received</p>
        <h1>Thank you. Your resume has been received.</h1>
        <p>
          {leadId
            ? `Your confirmation id is ${leadId}.`
            : "Your confirmation id will appear after a successful submission."}
        </p>
        <Link className="secondary-link" href="/">
          Submit another Lead
        </Link>
      </section>
    </main>
  );
}
