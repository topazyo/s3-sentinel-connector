terraform {
  required_version = ">= 1.0.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
  }
}

provider "azurerm" {
  features {}
}

data "azurerm_client_config" "current" {}

locals {
  subnet_map = zipmap(
    var.network_config.subnet_names,
    var.network_config.subnet_prefixes,
  )
}

resource "azurerm_resource_group" "rg" {
  name     = "s3-sentinel-connector-${var.environment}-rg"
  location = var.location
  tags     = var.tags
}

resource "azurerm_virtual_network" "vnet" {
  name                = "s3-sentinel-${var.environment}-vnet"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  address_space       = var.network_config.vnet_address_space
  tags                = var.tags
}

resource "azurerm_subnet" "subnets" {
  for_each             = local.subnet_map
  name                 = each.key
  resource_group_name  = azurerm_resource_group.rg.name
  virtual_network_name = azurerm_virtual_network.vnet.name
  address_prefixes     = [each.value]
}

resource "azurerm_key_vault" "kv" {
  name                = "s3-sentinel-${var.environment}-kv"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  tenant_id           = data.azurerm_client_config.current.tenant_id
  sku_name            = "standard"

  purge_protection_enabled = true

  network_acls {
    default_action = "Deny"
    bypass         = "AzureServices"
    ip_rules       = var.allowed_ip_ranges
  }

  tags = var.tags
}

resource "azurerm_container_registry" "acr" {
  name                = "s3sentinel${var.environment}acr"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  sku                 = "Standard"
  admin_enabled       = false
  tags                = var.tags
}

resource "azurerm_log_analytics_workspace" "law" {
  name                = "s3-sentinel-${var.environment}-law"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  sku                 = var.monitoring_config.log_analytics_sku
  retention_in_days   = var.monitoring_config.retention_days
  tags                = var.tags
}

resource "azurerm_log_analytics_solution" "sentinel" {
  solution_name         = "SecurityInsights"
  location              = azurerm_resource_group.rg.location
  resource_group_name   = azurerm_resource_group.rg.name
  workspace_resource_id = azurerm_log_analytics_workspace.law.id
  workspace_name        = azurerm_log_analytics_workspace.law.name

  plan {
    publisher = "Microsoft"
    product   = "OMSGallery/SecurityInsights"
  }

  tags = var.tags
}

resource "azurerm_monitor_data_collection_endpoint" "dce" {
  name                = "s3-sentinel-${var.environment}-dce"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  kind                = "Linux"
  tags                = var.tags
}

resource "azurerm_monitor_data_collection_rule" "dcr" {
  name                        = "s3-sentinel-${var.environment}-dcr"
  location                    = azurerm_resource_group.rg.location
  resource_group_name         = azurerm_resource_group.rg.name
  data_collection_endpoint_id = azurerm_monitor_data_collection_endpoint.dce.id
  kind                        = "Linux"

  destinations {
    log_analytics {
      workspace_resource_id = azurerm_log_analytics_workspace.law.id
      name                  = "law-destination"
    }
  }

  data_flow {
    streams      = ["Custom-FirewallLogs", "Custom-VpnLogs"]
    destinations = ["law-destination"]
  }

  stream_declaration {
    stream_name = "Custom-FirewallLogs"

    column {
      name = "TimeGenerated"
      type = "datetime"
    }

    column {
      name = "SourceIP"
      type = "string"
    }

    column {
      name = "DestinationIP"
      type = "string"
    }

    column {
      name = "Action"
      type = "string"
    }

    column {
      name = "Protocol"
      type = "string"
    }

    column {
      name = "SourcePort"
      type = "int"
    }

    column {
      name = "DestinationPort"
      type = "int"
    }

    column {
      name = "BytesTransferred"
      type = "long"
    }
  }

  stream_declaration {
    stream_name = "Custom-VpnLogs"

    column {
      name = "TimeGenerated"
      type = "datetime"
    }

    column {
      name = "UserPrincipalName"
      type = "string"
    }

    column {
      name = "SessionID"
      type = "string"
    }

    column {
      name = "ClientIP"
      type = "string"
    }

    column {
      name = "BytesIn"
      type = "long"
    }

    column {
      name = "BytesOut"
      type = "long"
    }

    column {
      name = "ConnectionDuration"
      type = "int"
    }
  }

  tags = var.tags
}

resource "azurerm_application_insights" "appinsights" {
  name                = "s3-sentinel-${var.environment}-ai"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  application_type    = "web"
  workspace_id        = azurerm_log_analytics_workspace.law.id
  tags                = var.tags
}

resource "azurerm_kubernetes_cluster" "aks" {
  name                = "s3-sentinel-${var.environment}-aks"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  dns_prefix          = "s3sentinel${var.environment}"
  kubernetes_version  = var.aks_config.kubernetes_version

  default_node_pool {
    name                 = "default"
    node_count           = var.aks_config.node_count
    vm_size              = var.aks_config.vm_size
    auto_scaling_enabled = true
    min_count            = var.aks_config.min_nodes
    max_count            = var.aks_config.max_nodes
    vnet_subnet_id       = azurerm_subnet.subnets[var.network_config.subnet_names[0]].id
  }

  identity {
    type = "SystemAssigned"
  }

  oms_agent {
    log_analytics_workspace_id = azurerm_log_analytics_workspace.law.id
  }

  tags = var.tags
}

resource "azurerm_role_assignment" "aks_acr_pull" {
  scope                = azurerm_container_registry.acr.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_kubernetes_cluster.aks.kubelet_identity[0].object_id
}

resource "azurerm_role_assignment" "aks_key_vault_secrets_user" {
  scope                = azurerm_key_vault.kv.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_kubernetes_cluster.aks.kubelet_identity[0].object_id
}
