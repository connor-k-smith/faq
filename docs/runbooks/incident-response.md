# Incident Response

Owner: FAQ operations. Security incidents also notify the deployment security owner.

1. Acknowledge the alert, assign an incident commander, severity, timeline, and communications owner.
2. Preserve structured logs and identify the affected environment, service revision, database instance, Project scope, and credentials without copying bearer tokens.
3. Contain: revoke compromised invitations, disable a service revision, restrict IAM, or suspend traffic as appropriate.
4. Recover using an immutable known-good image and, only when required, the database restore runbook.
5. Validate public/operator route isolation, Project authorization, token-log absence, migrations, and core journey before resolving.
6. Publish a blameless review with impact, detection gap, root cause, corrective owners, and due dates.
