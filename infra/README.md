# GCP Infrastructure

Terraform creates Cloud SQL, Firebase/Identity Platform, three Cloud Run services, a migration
job, Scheduler, resource-scoped secrets, IAM, and monitoring. Services share one immutable image.
Public grants `roles/run.invoker` to `allUsers` because bearer links and Firebase login are
application-authenticated routes. Operator and jobs remain protected by Cloud Run IAM.

Each Terraform state represents one deployment. Set `project_id` and the other deployment-specific
values in an uncommitted `infra/terraform.tfvars`; resource names use the `faq-production` prefix.

## State bootstrap

Generated SQL passwords and the session secret necessarily exist in
Terraform state. Create a versioned, uniformly bucket-level-access GCS bucket with public access
prevention before first use, restrict its IAM to Terraform operators, then initialize with:

```sh
terraform -chdir=infra init \
  -backend-config=bucket=FAQ_TERRAFORM_STATE_BUCKET \
  -backend-config=prefix=faq/production
```

Use `terraform init -backend=false` only for validation. Do not output, commit, or pass generated
credentials on command lines. Keep `terraform.tfvars` uncommitted and permissions-restricted.

Set deployment values in your shell and create the state bucket once. Bucket names are global, so
choose a unique value:

```sh
export FAQ_GCP_PROJECT="your-gcp-project-id"
export FAQ_GCP_REGION="us-central1"
export FAQ_TERRAFORM_STATE_BUCKET="your-unique-terraform-state-bucket"

gcloud storage buckets create "gs://${FAQ_TERRAFORM_STATE_BUCKET}" \
  --project="${FAQ_GCP_PROJECT}" \
  --location="${FAQ_GCP_REGION}" \
  --uniform-bucket-level-access \
  --public-access-prevention
gcloud storage buckets update "gs://${FAQ_TERRAFORM_STATE_BUCKET}" --versioning
terraform -chdir=infra init \
  -backend-config="bucket=${FAQ_TERRAFORM_STATE_BUCKET}" \
  -backend-config=prefix=faq/production
```

## Existing Firebase resources

If the Firebase project or web app already exists, import it after `terraform init` and before the
first plan so Terraform adopts it instead of trying to create duplicates. Obtain the web app ID
from Firebase and keep it in a shell variable:

```sh
export FAQ_FIREBASE_WEB_APP_ID="1:000000000000:web:replace-with-your-app-id"
terraform -chdir=infra import google_firebase_project.main \
  "projects/${FAQ_GCP_PROJECT}"
terraform -chdir=infra import google_firebase_web_app.main \
  "projects/${FAQ_GCP_PROJECT}/webApps/${FAQ_FIREBASE_WEB_APP_ID}"
```

## First deployment

Cloud Run URLs do not exist until the first service deployment, while the application requires
those URLs at startup. Use the temporary `bootstrap.invalid` values in the example for the first
apply, then immediately replace them with the Terraform outputs and apply again.

1. Copy `terraform.tfvars.example` to the ignored `terraform.tfvars` and fill in the human values.
2. Create only the enabled APIs and Artifact Registry repository:

```sh
terraform -chdir=infra apply \
  -target=google_project_service.required \
  -target=google_artifact_registry_repository.app
gcloud auth configure-docker "${FAQ_GCP_REGION}-docker.pkg.dev"
docker build --platform linux/amd64 \
  -t "${FAQ_GCP_REGION}-docker.pkg.dev/${FAQ_GCP_PROJECT}/faq/app:bootstrap" .
docker push "${FAQ_GCP_REGION}-docker.pkg.dev/${FAQ_GCP_PROJECT}/faq/app:bootstrap"
```

3. Resolve the pushed digest and put the resulting `.../app@sha256:...` reference in `image`:

```sh
gcloud artifacts docker images describe \
  "${FAQ_GCP_REGION}-docker.pkg.dev/${FAQ_GCP_PROJECT}/faq/app:bootstrap" \
  --format='value(image_summary.fully_qualified_digest)'
```

4. Create the database and migration job first, then execute the migration before creating services
   whose startup probes require the current schema:

```sh
terraform -chdir=infra apply -target=google_cloud_run_v2_job.migration
gcloud run jobs execute faq-production-migration \
  --project="${FAQ_GCP_PROJECT}" --region="${FAQ_GCP_REGION}" --wait
```

5. Run `terraform -chdir=infra plan -out=production.tfplan`, review it, and apply it. Capture
   `public_url`, `operator_url`, and `jobs_url` from `terraform -chdir=infra output`.
6. Set `public_base_url`, `operator_audience`, and `jobs_audience` to those respective outputs,
   plan, and apply again. Do not leave any `bootstrap.invalid` value deployed.

## Human prerequisites

- A billing-enabled GCP project and permissions to enable APIs and create these resources.
- A Firebase Authentication email/password user for each invited human user.
- The canonical `public_base_url`, and the deployed Cloud Run service URIs as `operator_audience`
  and `jobs_audience`. Cloud Run v2's provider-returned URI is authoritative; do not construct it.
- IAM member strings for `operator_invokers`, plus exact token emails for
  `operator_allowed_emails`. The two operator controls are intentionally separate.
- An immutable Artifact Registry image digest.

The Firebase web config is derived from the registered web app. No service-account key is created
or downloaded; Firebase Admin uses the Cloud Run service account through Application Default
Credentials.

## Database privileges

Cloud SQL users do not express PostgreSQL ownership or schema grants. The migration job runs
Alembic and deterministically reapplies runtime grants and default privileges as `faq_migration`.
Runtime services use `faq_runtime`; only the migration job receives migration credentials.

Cloud SQL uses the zonal shared-core `db-f1-micro` tier to keep costs appropriate for this small
internal tool. It is not highly available; recovery relies on automated backups and point-in-time
recovery. The database has no public IP; Cloud Run connects directly to its private address through
VPC egress and private service access, satisfying the project's `constraints/sql.restrictPublicIp`
policy.

## Connection budget

Cloud Run configures bounded SQLAlchemy pools: public uses at most 5 connections per instance
across 2 instances, operator 4 across 1 instance, and jobs 2 across 1 instance. The runtime
maximum is therefore 16 database connections, excluding the one-at-a-time migration job and
operator/database reserve. Revisit both pool values and the Cloud SQL connection limit before
raising instance counts or concurrency. Startup probes require current migrations through
`/readyz`; liveness remains the database-independent `/healthz`.
