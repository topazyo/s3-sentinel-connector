# deployment/terraform/environments/prod/main.tf

module "s3_sentinel_prod" {
  source = "../../modules/s3-sentinel"

  environment = var.environment
  location    = var.location

  network_config    = var.network_config
  aks_config        = var.aks_config
  monitoring_config = var.monitoring_config

  tags              = var.tags
  allowed_ip_ranges = var.allowed_ip_ranges
}

# Additional prod-specific resources
resource "azurerm_monitor_action_group" "prod_alerts" {
  name                = "s3-sentinel-prod-alerts"
  resource_group_name = module.s3_sentinel_prod.resource_group_name
  short_name          = "prodAlerts"

  email_receiver {
    name          = "oncall"
    email_address = "oncall@example.com"
  }

  sms_receiver {
    name         = "oncallsms"
    country_code = "1"
    phone_number = "2065555555"
  }
}

# Prod-specific monitoring rules
resource "azurerm_monitor_metric_alert" "prod_latency" {
  name                = "s3-sentinel-prod-latency-alert"
  resource_group_name = module.s3_sentinel_prod.resource_group_name
  scopes              = [module.s3_sentinel_prod.app_insights_id]
  description         = "Alert when processing latency exceeds threshold"

  criteria {
    metric_namespace = "azure.applicationinsights"
    metric_name      = "processingLatency"
    aggregation      = "Average"
    operator         = "GreaterThan"
    threshold        = 300 # 5 minutes
  }

  action {
    action_group_id = azurerm_monitor_action_group.prod_alerts.id
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