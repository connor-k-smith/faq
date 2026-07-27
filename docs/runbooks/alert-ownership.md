# Alert Ownership

Primary owner: FAQ operations. Secondary owner: deployment security owner.

| Signal | Severity | First action |
|---|---|---|
| Public service unavailable or sustained 5xx | High | Incident response; inspect revision and database availability |
| Respondent exchange spike | High | Check abuse and credential compromise; use revocation runbook |
| Migration failure | High | Stop promotion; preserve Job logs; use migration runbook |
| Database CPU, memory, connections, or disk over 80% | Medium | Inspect workload and pool limits; scale only after identifying cause |
| Backup failure or stale backup | High | Stop risky releases; restore backup health and schedule a restore test |
| Login failure spike | Medium | Inspect Identity Platform and invitation failures without logging tokens |
| Repeated transaction retries | Medium | Inspect lock contention and recent releases |

The Terraform `alert_email` notification channel must route to an actively monitored destination. Every alert policy must link to the applicable runbook and carry environment and owner labels.
