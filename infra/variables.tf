variable "project_id" {
  type = string
}

variable "region" {
  type    = string
  default = "us-central1"
}

variable "environment" {
  type    = string
  default = "production"
  validation {
    condition     = var.environment == "production"
    error_message = "this deployment supports only the production environment"
  }
}

variable "image" {
  description = "Immutable image digest shared by all services and the migration job."
  type        = string
  validation {
    condition     = can(regex("@sha256:[0-9a-f]{64}$", var.image))
    error_message = "image must be an immutable sha256 digest reference"
  }
}

variable "database_tier" {
  type    = string
  default = "db-f1-micro"
}

variable "organization_name" {
  type = string
}

variable "bootstrap_admin_email" {
  type = string
}

variable "operator_allowed_emails" {
  type = set(string)
  validation {
    condition     = length(var.operator_allowed_emails) > 0
    error_message = "at least one operator email is required"
  }
}

variable "operator_invokers" {
  description = "IAM members allowed to invoke operator, independently of the in-app email allowlist."
  type        = set(string)
  default     = []
}

variable "public_base_url" {
  description = "Canonical HTTPS URL used in respondent links and Firebase configuration."
  type        = string
  validation {
    condition     = startswith(var.public_base_url, "https://")
    error_message = "public_base_url must use HTTPS"
  }
}

variable "operator_audience" {
  description = "Expected OIDC audience for the IAM-only operator service. Usually its Cloud Run URI."
  type        = string
}

variable "jobs_audience" {
  description = "Expected Scheduler OIDC audience for the IAM-only jobs service. Usually its Cloud Run URI."
  type        = string
}

variable "alert_email" {
  type = string
}
