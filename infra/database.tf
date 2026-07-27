resource "random_password" "runtime_database" {
  length           = 40
  special          = true
  override_special = "-._~"
}

resource "random_password" "migration_database" {
  length           = 40
  special          = true
  override_special = "-._~"
}

resource "google_sql_database_instance" "main" {
  name                = "${local.prefix}-postgres"
  region              = var.region
  database_version    = "POSTGRES_17"
  deletion_protection = true

  settings {
    tier              = var.database_tier
    edition           = "ENTERPRISE"
    availability_type = "ZONAL"
    disk_type         = "PD_SSD"
    disk_autoresize   = true
    user_labels       = local.labels

    ip_configuration {
      ipv4_enabled                                  = false
      private_network                               = google_compute_network.main.id
      enable_private_path_for_google_cloud_services = true
    }
    backup_configuration {
      enabled                        = true
      start_time                     = "03:00"
      point_in_time_recovery_enabled = true
      transaction_log_retention_days = 7
      backup_retention_settings {
        retained_backups = 14
        retention_unit   = "COUNT"
      }
    }
    maintenance_window {
      day          = 7
      hour         = 4
      update_track = "stable"
    }
    insights_config {
      query_insights_enabled  = true
      record_application_tags = true
    }
  }
  depends_on = [google_project_service.required, google_service_networking_connection.private_services]
}

resource "google_sql_database" "app" {
  name     = "faq"
  instance = google_sql_database_instance.main.name
}

resource "google_sql_user" "runtime" {
  name     = "faq_runtime"
  instance = google_sql_database_instance.main.name
  password = random_password.runtime_database.result
}

resource "google_sql_user" "migration" {
  name     = "faq_migration"
  instance = google_sql_database_instance.main.name
  password = random_password.migration_database.result
}

locals {
  runtime_database_url   = "postgresql+psycopg://${google_sql_user.runtime.name}:${urlencode(random_password.runtime_database.result)}@${google_sql_database_instance.main.private_ip_address}:5432/${google_sql_database.app.name}"
  migration_database_url = "postgresql+psycopg://${google_sql_user.migration.name}:${urlencode(random_password.migration_database.result)}@${google_sql_database_instance.main.private_ip_address}:5432/${google_sql_database.app.name}"
}
