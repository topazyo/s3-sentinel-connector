# deployment/terraform/environments/dev/terraform.tfvars

environment = "dev"
location    = "eastus2"

# Network configuration
network_config = {
  vnet_address_space = ["10.0.0.0/16"]
  subnet_prefixes    = ["10.0.1.0/24", "10.0.2.0/24"]
  subnet_names       = ["aks-subnet", "app-subnet"]
}

# AKS configuration
aks_config = {
  kubernetes_version = "1.23.8"
  node_count         = 2
  vm_size            = "Standard_D2s_v3"
  min_nodes          = 2
  max_nodes          = 4
}

# Monitoring configuration
monitoring_config = {
  retention_days    = 30
  log_analytics_sku = "PerGB2018"
  enable_prometheus = true
  metrics_retention = "P30D"
}

# Tags
tags = {
  Environment = "dev"
  ManagedBy   = "terraform"
  Project     = "s3-sentinel-connector"
}

# Access control
allowed_ip_ranges = ["10.0.0.0/8"]