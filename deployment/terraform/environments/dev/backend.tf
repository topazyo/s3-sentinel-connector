terraform {
  backend "azurerm" {
    resource_group_name  = "tfstate-dev-rg"
    storage_account_name = "s3sentineldevtfstate"
    container_name       = "tfstate"
    key                  = "s3-sentinel-connector-dev.tfstate"
  }
}
