resource "google_monitoring_notification_channel" "operations" {
  display_name = "FAQ ${var.environment} operations"
  type         = "email"
  labels       = { email_address = var.alert_email }
  user_labels  = local.labels
}

resource "google_logging_metric" "token_exchange_failures" {
  name   = "${local.prefix}-respondent-exchange-failed"
  filter = "jsonPayload.event=\"respondent_exchange_failed\""
}

resource "google_monitoring_alert_policy" "token_exchange_spike" {
  display_name          = "FAQ ${var.environment}: respondent token exchange spike"
  combiner              = "OR"
  notification_channels = [google_monitoring_notification_channel.operations.name]
  documentation { content = "Owner: FAQ operations. Runbook: docs/runbooks/credential-revocation.md" }
  conditions {
    display_name = "More than 20 failed exchanges in five minutes"
    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.token_exchange_failures.name}\" AND resource.type=\"cloud_run_revision\""
      comparison      = "COMPARISON_GT"
      threshold_value = 20
      duration        = "0s"
      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_SUM"
      }
    }
  }
  user_labels = local.labels
}

resource "google_monitoring_alert_policy" "database_cpu" {
  display_name          = "FAQ ${var.environment}: database CPU saturation"
  combiner              = "OR"
  notification_channels = [google_monitoring_notification_channel.operations.name]
  documentation { content = "Owner: FAQ operations. Runbook: docs/runbooks/incident-response.md" }
  conditions {
    display_name = "Cloud SQL CPU over 80 percent"
    condition_threshold {
      filter          = "resource.type=\"cloudsql_database\" AND metric.type=\"cloudsql.googleapis.com/database/cpu/utilization\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0.8
      duration        = "600s"
      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_MEAN"
      }
    }
  }
  user_labels = local.labels
}

resource "google_monitoring_alert_policy" "scheduler_failures" {
  display_name          = "FAQ ${var.environment}: scheduler delivery failures"
  combiner              = "OR"
  notification_channels = [google_monitoring_notification_channel.operations.name]
  documentation { content = "Owner: FAQ operations. Runbook: docs/runbooks/incident-response.md" }
  conditions {
    display_name = "Scheduler job has a failed attempt"
    condition_threshold {
      filter          = "resource.type=\"cloud_scheduler_job\" AND resource.label.job_id=\"${google_cloud_scheduler_job.jobs_tick.name}\" AND metric.type=\"logging.googleapis.com/user/${google_logging_metric.scheduler_failures.name}\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"
      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_SUM"
      }
    }
  }
  user_labels = local.labels
}

resource "google_logging_metric" "scheduler_failures" {
  name   = "${local.prefix}-scheduler-failures"
  filter = "resource.type=\"cloud_scheduler_job\" AND resource.labels.job_id=\"${google_cloud_scheduler_job.jobs_tick.name}\" AND severity>=ERROR"
}
