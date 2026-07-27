resource "random_password" "session" {
  length  = 64
  special = false
}

resource "google_secret_manager_secret" "runtime_database_url" {
  secret_id = "${local.prefix}-runtime-database-url"
  labels    = local.labels
  replication {
    auto {}
  }
  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret_version" "runtime_database_url" {
  secret      = google_secret_manager_secret.runtime_database_url.id
  secret_data = local.runtime_database_url
}

resource "google_secret_manager_secret" "migration_database_url" {
  secret_id = "${local.prefix}-migration-database-url"
  labels    = local.labels
  replication {
    auto {}
  }
  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret_version" "migration_database_url" {
  secret      = google_secret_manager_secret.migration_database_url.id
  secret_data = local.migration_database_url
}

resource "google_secret_manager_secret" "session" {
  secret_id = "${local.prefix}-session-secret"
  labels    = local.labels
  replication {
    auto {}
  }
  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret_version" "session" {
  secret      = google_secret_manager_secret.session.id
  secret_data = random_password.session.result
}

resource "google_secret_manager_secret_iam_member" "runtime_database" {
  for_each = {
    public   = google_service_account.public.email
    operator = google_service_account.operator.email
    jobs     = google_service_account.jobs.email
  }
  secret_id = google_secret_manager_secret.runtime_database_url.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${each.value}"
}

resource "google_secret_manager_secret_iam_member" "runtime_session" {
  secret_id = google_secret_manager_secret.session.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.public.email}"
}

resource "google_secret_manager_secret_iam_member" "migration_database" {
  secret_id = google_secret_manager_secret.migration_database_url.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.migration.email}"
}
