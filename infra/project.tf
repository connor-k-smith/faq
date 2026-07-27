locals {
  prefix = "faq-${var.environment}"
  labels = {
    application = "faq"
    environment = var.environment
    owner       = "faq-operations"
  }
  public_service_name   = "${local.prefix}-public"
  operator_service_name = "${local.prefix}-operator"
  jobs_service_name     = "${local.prefix}-jobs"
}

resource "google_project_service" "required" {
  for_each = toset([
    "artifactregistry.googleapis.com",
    "aiplatform.googleapis.com",
    "cloudscheduler.googleapis.com",
    "cloudfunctions.googleapis.com",
    "compute.googleapis.com",
    "firebase.googleapis.com",
    "iam.googleapis.com",
    "identitytoolkit.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "servicenetworking.googleapis.com",
    "serviceusage.googleapis.com",
    "sqladmin.googleapis.com",
  ])
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_project_iam_member" "public_vertex_ai" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.public.email}"
}

resource "google_project_iam_member" "public_firebase_auth_viewer" {
  project = var.project_id
  role    = "roles/firebaseauth.viewer"
  member  = "serviceAccount:${google_service_account.public.email}"
}

resource "google_artifact_registry_repository" "app" {
  location      = var.region
  repository_id = "faq"
  description   = "FAQ production container images"
  format        = "DOCKER"
  labels        = local.labels
  depends_on    = [google_project_service.required]
}
