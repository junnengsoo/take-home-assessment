# Lead Intake

The lead-intake context captures prospect submissions and the attorneys' follow-up work on those submissions.

## Language

**Prospect**:
A person who submits their contact details and résumé for consideration. A Prospect may create more than one Lead.
_Avoid_: Applicant, candidate, customer

**Lead**:
A single completed submission from a Prospect. Each submission is a distinct Lead even when its email matches an earlier submission.
_Avoid_: Prospect, application

**Possible Duplicate**:
A Lead whose normalized email matches at least one earlier Lead. It remains independent and is neither blocked nor merged with those earlier Leads.
_Avoid_: Duplicate Prospect, repeated Lead

**Submission Attempt**:
One deliberate attempt by a Prospect to create a Lead. Technical retries of the same Submission Attempt return the same result, while a later deliberate attempt creates another Lead.
_Avoid_: Request, duplicate Lead

**Attorney**:
An authenticated internal user who reviews Leads and records follow-up activity.
_Avoid_: Admin, agent, staff user

**Assignment**:
The Attorney accountable for ensuring a Lead is followed up. Assignment does not restrict other Attorneys from viewing the Lead or recording work on it.
_Avoid_: Ownership, permission, exclusive assignee

**Fallback Intake Address**:
The internal email recipient notified when no Attorney account is available for round-robin Assignment. It does not become the Lead's Assignment.
_Avoid_: Default Attorney, assigned mailbox

**Lead Status**:
The current follow-up state of a Lead: `PENDING` or `REACHED_OUT`. It is derived from the Lead's ordered Status Changes.
_Avoid_: Lead state, application status

**Status Change**:
An append-only record that the system or an Attorney set a Lead's status at a particular time. Submission creates the initial `PENDING` Status Change; reversing a Lead later adds another Status Change rather than deleting history.
_Avoid_: Status overwrite, action
