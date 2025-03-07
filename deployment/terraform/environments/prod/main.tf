# deployment/terraform/environments/prod/main.tf

module "s3_sentinel_prod" {
  source = "../../modules/s3-sentinel"

  environment = var.environment
  location    = var.location
  
  network_config     = var.network_config
  aks_config        = var.aks_config
  monitoring_config = var.monitoring_config
  
  tags              = var.tags
  allowed_ip_ranges = var.allowed_ip_ranges

  # Prod-specific configurations
  enable_backup = true
  backup_retention_days = 30
  enable_geo_redundancy = true
  monitoring_interval = "60s"
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