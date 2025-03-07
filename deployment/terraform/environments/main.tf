# deployment/terraform/main.tf

terraform {
  required_version = ">= 1.0.0"
  
  backend "azurerm" {
    resource_group_name  = "terraform-state-rg"
    storage_account_name = "tfstate${var.environment}"
    container_name       = "tfstate"
    key                 = "s3-sentinel-connector.tfstate"
  }
}

# Azure Provider configuration
provider "azurerm" {
  features {}
}

# Create Resource Group
resource "azurerm_resource_group" "rg" {
  name     = "s3-sentinel-connector-${var.environment}-rg"
  location = var.location
  
  tags = {
    Environment = var.environment
    Application = "s3-sentinel-connector"
    Terraform   = "true"
  }
}

# Create Key Vault
resource "azurerm_key_vault" "kv" {
  name                = "s3-sentinel-${var.environment}-kv"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  tenant_id          = data.azurerm_client_config.current.tenant_id
  sku_name           = "standard"

  purge_protection_enabled = true
  
  network_acls {
    default_action = "Deny"
    bypass         = "AzureServices"
    ip_rules       = var.allowed_ip_ranges
  }
}

# Create Azure Container Registry
resource "azurerm_container_registry" "acr" {
  name                = "s3sentinel${var.environment}acr"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  sku                 = "Standard"
  admin_enabled       = true
}

# Create Log Analytics Workspace
resource "azurerm_log_analytics_workspace" "law" {
  name                = "s3-sentinel-${var.environment}-law"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
}

# Create Application Insights
resource "azurerm_application_insights" "appinsights" {
  name                = "s3-sentinel-${var.environment}-ai"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  application_type    = "web"
  workspace_id        = azurerm_log_analytics_workspace.law.id
}

# Create AKS Cluster
resource "azurerm_kubernetes_cluster" "aks" {
  name                = "s3-sentinel-${var.environment}-aks"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  dns_prefix          = "s3sentinel${var.environment}"

  default_node_pool {
    name       = "default"
    node_count = var.node_count
    vm_size    = var.node_size
    
    enable_auto_scaling = true
    min_count          = var.min_nodes
    max_count          = var.max_nodes
  }

  identity {
    type = "SystemAssigned"
  }

  addon_profile {
    oms_agent {
      enabled                    = true
      log_analytics_workspace_id = azurerm_log_analytics_workspace.law.id
    }
  }
}