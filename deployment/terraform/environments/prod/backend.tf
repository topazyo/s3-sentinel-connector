terraform {
  backend "azurerm" {
    resource_group_name  = "tfstate-prod-rg"
    storage_account_name = "s3sentinelprodtfstate"
    container_name       = "tfstate"
    key                  = "s3-sentinel-connector-prod.tfstate"
  }
}
