# deployment/terraform/environments/dev/main.tf

module "s3_sentinel_dev" {
  source = "../../modules/s3-sentinel"

  environment = var.environment
  location    = var.location

  network_config    = var.network_config
  aks_config        = var.aks_config
  monitoring_config = var.monitoring_config

  tags              = var.tags
  allowed_ip_ranges = var.allowed_ip_ranges
}

# Additional dev-specific resources
resource "azurerm_monitor_action_group" "dev_alerts" {
  name                = "s3-sentinel-dev-alerts"
  resource_group_name = module.s3_sentinel_dev.resource_group_name
  short_name          = "devAlerts"

  email_receiver {
    name          = "devteam"
    email_address = "devteam@example.com"
  }
}

variable "environment" {
  type        = string
  description = "Environment name"
}

variable "location" {
  type        = string
  description = "Azure region"
}

variable "network_config" {
  type = object({
    vnet_address_space = list(string)
    subnet_prefixes    = list(string)
    subnet_names       = list(string)
  })
  description = "Network configuration"
}

variable "aks_config" {
  type = object({
    kubernetes_version = string
    node_count         = number
    vm_size            = string
    min_nodes          = number
    max_nodes          = number
  })
  description = "AKS configuration"
}

variable "monitoring_config" {
  type = object({
    retention_days    = number
    log_analytics_sku = string
    enable_prometheus = bool
    metrics_retention = string
  })
  description = "Monitoring configuration"
}

variable "tags" {
  type        = map(string)
  description = "Resource tags"
}

variable "allowed_ip_ranges" {
  type        = list(string)
  description = "Allowed IP ranges"
}