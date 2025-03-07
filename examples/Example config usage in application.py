# Example usage in application

async def main():
    # Initialize configuration manager
    config_manager = ConfigManager(
        config_path="./config",
        environment="prod",
        vault_url="https://your-keyvault.vault.azure.net/",
        enable_hot_reload=True
    )
    
    # Get component configurations
    aws_config = config_manager.get_aws_config()
    sentinel_config = config_manager.get_sentinel_config()
    monitoring_config = config_manager.get_monitoring_config()
    
    # Initialize components with configurations
    s3_handler = S3Handler(
        aws_access_key=await config_manager.get_secret('aws-access-key'),
        aws_secret_key=await config_manager.get_secret('aws-secret-key'),
        region=aws_config.region,
        batch_size=aws_config.batch_size
    )
    
    # Use configurations in components
    sentinel_router = SentinelRouter(
        dcr_endpoint=sentinel_config.dcr_endpoint,
        rule_id=sentinel_config.rule_id,
        stream_name=sentinel_config.stream_name
    )
    
    # Monitor configuration changes
    while True:
        # Your application logic here
        await asyncio.sleep(60)