resource "google_service_account" "public" {
  account_id   = "${local.prefix}-public"
  display_name = "FAQ public runtime (${var.environment})"
}

resource "google_service_account" "operator" {
  account_id   = "${local.prefix}-operator"
  display_name = "FAQ operator runtime (${var.environment})"
}

resource "google_service_account" "jobs" {
  account_id   = "${local.prefix}-jobs"
  display_name = "FAQ jobs runtime (${var.environment})"
}

resource "google_service_account" "migration" {
  account_id   = "${local.prefix}-migration"
  display_name = "FAQ database migration (${var.environment})"
}

locals {
  public_environment = {
    FAQ_ENVIRONMENT           = "production"
    FAQ_ORGANIZATION_NAME     = var.organization_name
    FAQ_BOOTSTRAP_ADMIN_EMAIL = var.bootstrap_admin_email
    FAQ_PUBLIC_BASE_URL       = var.public_base_url
    FAQ_FIREBASE_API_KEY      = local.firebase_api_key
    FAQ_FIREBASE_AUTH_DOMAIN  = local.firebase_auth_domain
    FAQ_FIREBASE_PROJECT_ID   = local.firebase_project_id
    FAQ_FIREBASE_APP_ID       = local.firebase_app_id
    FAQ_DATABASE_POOL_SIZE    = "4"
    FAQ_DATABASE_MAX_OVERFLOW = "1"
    FAQ_DATABASE_POOL_TIMEOUT = "5"
    FAQ_DATABASE_POOL_RECYCLE = "1800"
  }
  operator_environment = {
    FAQ_ENVIRONMENT             = "production"
    FAQ_OPERATOR_AUDIENCE       = var.operator_audience
    FAQ_OPERATOR_ALLOWED_EMAILS = jsonencode(sort(tolist(var.operator_allowed_emails)))
    FAQ_DATABASE_POOL_SIZE      = "3"
    FAQ_DATABASE_MAX_OVERFLOW   = "1"
    FAQ_DATABASE_POOL_TIMEOUT   = "5"
    FAQ_DATABASE_POOL_RECYCLE   = "1800"
  }
  jobs_environment = {
    FAQ_ENVIRONMENT           = "production"
    FAQ_JOBS_AUDIENCE         = var.jobs_audience
    FAQ_JOBS_CALLER_EMAIL     = google_service_account.scheduler.email
    FAQ_DATABASE_POOL_SIZE    = "2"
    FAQ_DATABASE_MAX_OVERFLOW = "0"
    FAQ_DATABASE_POOL_TIMEOUT = "5"
    FAQ_DATABASE_POOL_RECYCLE = "1800"
  }
}

resource "google_cloud_run_v2_service" "public" {
  name                = local.public_service_name
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = var.environment == "production"
  labels              = local.labels
  lifecycle { ignore_changes = [scaling] }

  template {
    service_account                  = google_service_account.public.email
    max_instance_request_concurrency = 40
    vpc_access {
      network_interfaces {
        network    = google_compute_network.main.name
        subnetwork = google_compute_subnetwork.cloud_run.name
      }
      egress = "PRIVATE_RANGES_ONLY"
    }
    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }
    containers {
      image   = var.image
      command = ["/app/docker-entrypoint.sh"]
      args    = ["app.main:app"]
      ports { container_port = 8080 }
      dynamic "env" {
        for_each = local.public_environment
        content {
          name  = env.key
          value = env.value
        }
      }
      env {
        name = "FAQ_DATABASE_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.runtime_database_url.secret_id
            version = google_secret_manager_secret_version.runtime_database_url.version
          }
        }
      }
      env {
        name = "FAQ_SESSION_SECRET"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.session.secret_id
            version = google_secret_manager_secret_version.session.version
          }
        }
      }
      startup_probe {
        failure_threshold = 12
        period_seconds    = 5
        timeout_seconds   = 2
        http_get {
          path = "/readyz"
          port = 8080
        }
      }
      liveness_probe {
        initial_delay_seconds = 10
        period_seconds        = 30
        timeout_seconds       = 2
        http_get {
          path = "/healthz"
          port = 8080
        }
      }
      resources {
        limits            = { cpu = "1", memory = "512Mi" }
        cpu_idle          = true
        startup_cpu_boost = true
      }
    }
  }
  depends_on = [google_project_service.required, google_secret_manager_secret_iam_member.runtime_database, google_secret_manager_secret_iam_member.runtime_session]
}

resource "google_cloud_run_v2_service" "operator" {
  name                = local.operator_service_name
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = var.environment == "production"
  labels              = local.labels
  lifecycle { ignore_changes = [scaling] }

  template {
    service_account = google_service_account.operator.email
    vpc_access {
      network_interfaces {
        network    = google_compute_network.main.name
        subnetwork = google_compute_subnetwork.cloud_run.name
      }
      egress = "PRIVATE_RANGES_ONLY"
    }
    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }
    containers {
      image   = var.image
      command = ["/app/docker-entrypoint.sh"]
      args    = ["app.operator_main:app"]
      ports { container_port = 8080 }
      dynamic "env" {
        for_each = local.operator_environment
        content {
          name  = env.key
          value = env.value
        }
      }
      env {
        name = "FAQ_DATABASE_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.runtime_database_url.secret_id
            version = google_secret_manager_secret_version.runtime_database_url.version
          }
        }
      }
      startup_probe {
        failure_threshold = 12
        period_seconds    = 5
        timeout_seconds   = 2
        http_get {
          path = "/readyz"
          port = 8080
        }
      }
      liveness_probe {
        initial_delay_seconds = 10
        period_seconds        = 30
        timeout_seconds       = 2
        http_get {
          path = "/healthz"
          port = 8080
        }
      }
      resources {
        limits            = { cpu = "1", memory = "512Mi" }
        cpu_idle          = true
        startup_cpu_boost = true
      }
    }
  }
  depends_on = [google_project_service.required, google_secret_manager_secret_iam_member.runtime_database]
}

resource "google_cloud_run_v2_service" "jobs" {
  name                = local.jobs_service_name
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_INTERNAL_ONLY"
  deletion_protection = var.environment == "production"
  labels              = local.labels
  lifecycle { ignore_changes = [scaling] }

  template {
    service_account = google_service_account.jobs.email
    vpc_access {
      network_interfaces {
        network    = google_compute_network.main.name
        subnetwork = google_compute_subnetwork.cloud_run.name
      }
      egress = "PRIVATE_RANGES_ONLY"
    }
    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }
    containers {
      image   = var.image
      command = ["/app/docker-entrypoint.sh"]
      args    = ["app.jobs_main:app"]
      ports { container_port = 8080 }
      dynamic "env" {
        for_each = local.jobs_environment
        content {
          name  = env.key
          value = env.value
        }
      }
      env {
        name = "FAQ_DATABASE_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.runtime_database_url.secret_id
            version = google_secret_manager_secret_version.runtime_database_url.version
          }
        }
      }
      startup_probe {
        failure_threshold = 12
        period_seconds    = 5
        timeout_seconds   = 2
        http_get {
          path = "/readyz"
          port = 8080
        }
      }
      liveness_probe {
        initial_delay_seconds = 10
        period_seconds        = 30
        timeout_seconds       = 2
        http_get {
          path = "/healthz"
          port = 8080
        }
      }
      resources {
        limits            = { cpu = "1", memory = "512Mi" }
        cpu_idle          = true
        startup_cpu_boost = true
      }
    }
  }
  depends_on = [google_project_service.required, google_secret_manager_secret_iam_member.runtime_database]
}

resource "google_cloud_run_v2_job" "migration" {
  name                = "${local.prefix}-migration"
  location            = var.region
  deletion_protection = var.environment == "production"
  labels              = local.labels
  template {
    template {
      service_account = google_service_account.migration.email
      max_retries     = 0
      timeout         = "1800s"
      vpc_access {
        network_interfaces {
          network    = google_compute_network.main.name
          subnetwork = google_compute_subnetwork.cloud_run.name
        }
        egress = "PRIVATE_RANGES_ONLY"
      }
      containers {
        image   = var.image
        command = ["/app/.venv/bin/python"]
        args    = ["-m", "app.migrate"]
        env {
          name  = "FAQ_ENVIRONMENT"
          value = "production"
        }
        env {
          name = "FAQ_DATABASE_URL"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.migration_database_url.secret_id
              version = google_secret_manager_secret_version.migration_database_url.version
            }
          }
        }
        resources {
          limits = { cpu = "1", memory = "512Mi" }
        }
      }
    }
  }
  depends_on = [google_project_service.required, google_secret_manager_secret_iam_member.migration_database, google_sql_user.runtime]
}

resource "google_cloud_run_v2_service_iam_member" "public" {
  project  = var.project_id
  location = google_cloud_run_v2_service.public.location
  name     = google_cloud_run_v2_service.public.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service_iam_member" "operator" {
  for_each = var.operator_invokers
  project  = var.project_id
  location = google_cloud_run_v2_service.operator.location
  name     = google_cloud_run_v2_service.operator.name
  role     = "roles/run.invoker"
  member   = each.value
}
