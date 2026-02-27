# deployment/terraform/modules/s3-sentinel/variables.tf

variable "environment" {
  type        = string
  description = "Environment name (dev/prod)"
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
  description = "Allowed IP ranges for access"
}