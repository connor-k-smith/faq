# Emergency Credential Revocation

Owner: FAQ operations.

1. Confirm the exact AskRecipient ID and incident reason. Never paste the raw invitation token into tickets or logs.
2. Invoke the IAM-only operator endpoint `POST /admin/ask-recipients/{id}/revoke` with an authorized identity token.
3. Verify `revoked=true`, `session_version` increased once, pending/blocked Assignments were withdrawn, and an `ask_recipient.revoked` Event was written.
4. Verify both the original token and a previously exchanged cookie no longer grant access.
5. Repeated revocation is safe and must not increment the version again. The operator service cannot reissue credentials.
