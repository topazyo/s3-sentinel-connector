# deployment/terraform/environments/dev/main.tf

module "s3_sentinel_dev" {
  source = "../../modules/s3-sentinel"

  environment = var.environment
  location    = var.location
  
  network_config     = var.network_config
  aks_config        = var.aks_config
  monitoring_config = var.monitoring_config
  
  tags              = var.tags
  allowed_ip_ranges = var.allowed_ip_ranges

  # Dev-specific configurations
  enable_debug_logging = true
  backup_retention_days = 7
  monitoring_interval = "30s"
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