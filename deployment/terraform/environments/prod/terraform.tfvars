# deployment/terraform/environments/prod/terraform.tfvars

environment = "prod"
location    = "eastus2"

# Network configuration
network_config = {
  vnet_address_space = ["172.16.0.0/16"]
  subnet_prefixes    = ["172.16.1.0/24", "172.16.2.0/24"]
  subnet_names       = ["aks-subnet", "app-subnet"]
}

# AKS configuration
aks_config = {
  kubernetes_version = "1.23.8"
  node_count        = 3
  vm_size           = "Standard_D4s_v3"
  min_nodes         = 3
  max_nodes         = 10
}

# Monitoring configuration
monitoring_config = {
  retention_days     = 90
  log_analytics_sku  = "PerGB2018"
  enable_prometheus  = true
  metrics_retention  = "P90D"
}

# Tags
tags = {
  Environment = "prod"
  ManagedBy   = "terraform"
  Project     = "s3-sentinel-connector"
}

# Access control
allowed_ip_ranges = ["10.0.0.0/8", "172.16.0.0/12"]