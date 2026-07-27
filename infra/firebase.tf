resource "google_firebase_project" "main" {
  provider   = google-beta
  project    = var.project_id
  depends_on = [google_project_service.required]
}

resource "google_firebase_web_app" "main" {
  provider     = google-beta
  project      = var.project_id
  display_name = "FAQ ${var.environment}"
  depends_on   = [google_firebase_project.main]
}

data "google_firebase_web_app_config" "main" {
  provider   = google-beta
  project    = var.project_id
  web_app_id = google_firebase_web_app.main.app_id
}

resource "google_identity_platform_config" "main" {
  project = var.project_id
  authorized_domains = [
    "${var.project_id}.firebaseapp.com",
    "${var.project_id}.web.app",
    trimsuffix(trimprefix(var.public_base_url, "https://"), "/"),
  ]
  sign_in {
    email {
      enabled           = true
      password_required = true
    }
    phone_number {
      enabled            = false
      test_phone_numbers = {}
    }
  }
  multi_tenant {
    allow_tenants = false
  }
  depends_on = [google_project_service.required, google_firebase_project.main]
}

locals {
  firebase_api_key     = data.google_firebase_web_app_config.main.api_key
  firebase_auth_domain = data.google_firebase_web_app_config.main.auth_domain
  firebase_project_id  = var.project_id
  firebase_app_id      = google_firebase_web_app.main.app_id
}
