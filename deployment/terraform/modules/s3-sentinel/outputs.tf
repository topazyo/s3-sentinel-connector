# deployment/terraform/modules/s3-sentinel/outputs.tf

output "resource_group_name" {
  value = azurerm_resource_group.rg.name
}

output "aks_cluster_name" {
  value = azurerm_kubernetes_cluster.aks.name
}

output "acr_login_server" {
  value = azurerm_container_registry.acr.login_server
}

output "app_insights_id" {
  value = azurerm_application_insights.appinsights.id
}

output "key_vault_name" {
  value = azurerm_key_vault.kv.name
}