# Environment Promotion

Owner: FAQ release owner. Production requires a second approver.

1. Validate application tests, Docker build, `terraform fmt -check`, and `terraform validate` on the pull request.
2. Build once and publish an image by digest. Do not rebuild between environments.
3. Apply the staging plan, run its migration Job, deploy the digest, and complete route isolation, IAM denial, token-log, browser, and export smoke tests.
4. Review and approve the production Terraform plan.
5. Confirm backup freshness, execute the production migration Job, and deploy the same digest.
6. Monitor alerts and logs through the agreed observation window; record plan, approver, migration execution, digest, and smoke-test evidence.

Staging and production use separate GCP projects, Terraform state, Cloud SQL instances, secrets, service accounts, domains, and notification routing.
