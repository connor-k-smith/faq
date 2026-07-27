resource "google_service_account" "scheduler" {
  account_id   = "${local.prefix}-scheduler"
  display_name = "FAQ Scheduler caller (${var.environment})"
}

resource "google_cloud_run_v2_service_iam_member" "scheduler_jobs" {
  project  = var.project_id
  location = google_cloud_run_v2_service.jobs.location
  name     = google_cloud_run_v2_service.jobs.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler.email}"
}

resource "google_cloud_scheduler_job" "jobs_tick" {
  name             = "${local.prefix}-jobs-tick"
  region           = var.region
  schedule         = "*/5 * * * *"
  time_zone        = "Etc/UTC"
  attempt_deadline = "300s"
  description      = "Run FAQ durable background work"

  retry_config {
    retry_count          = 3
    min_backoff_duration = "10s"
    max_backoff_duration = "60s"
    max_doublings        = 2
  }
  http_target {
    uri         = "${google_cloud_run_v2_service.jobs.uri}/jobs/tick"
    http_method = "POST"
    headers     = { "Content-Type" = "application/json" }
    body        = base64encode("{}")
    oidc_token {
      service_account_email = google_service_account.scheduler.email
      audience              = var.jobs_audience
    }
  }
  depends_on = [google_project_service.required, google_cloud_run_v2_service_iam_member.scheduler_jobs]
}
