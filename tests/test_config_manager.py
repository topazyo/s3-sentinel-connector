# tests/test_config_manager.py

import pytest
import os
import yaml
from src.config.config_manager import ConfigManager, ConfigurationError

class TestConfigManager:
    @pytest.fixture
    def test_config_path(self, tmp_path):
        """Create temporary config files for testing"""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        
        # Create base config
        base_config = {
            'aws': {
                'region': 'us-east-1',
                'batch_size': 1000
            },
            'sentinel': {
                'workspace_id': 'base-workspace',
                'retention_days': 90
            }
        }
        
        with open(config_dir / "base.yaml", 'w') as f:
            yaml.dump(base_config, f)
        
        # Create test environment config
        test_config = {
            'aws': {
                'bucket_name': 'test-bucket'
            },
            'sentinel': {
                'workspace_id': 'test-workspace'
            }
        }
        
        with open(config_dir / "test.yaml", 'w') as f:
            yaml.dump(test_config, f)
        
        return config_dir

    def test_load_config(self, test_config_path):
        """Test loading and merging configurations"""
        config_manager = ConfigManager(
            config_path=str(test_config_path),
            environment="test",
            enable_hot_reload=False
        )
        
        aws_config = config_manager.get_config('aws')
        assert aws_config['region'] == 'us-east-1'
        assert aws_config['bucket_name'] == 'test-bucket'
        assert aws_config['batch_size'] == 1000

    def test_environment_override(self, test_config_path):
        """Test environment-specific overrides"""
        config_manager = ConfigManager(
            config_path=str(test_config_path),
            environment="test",
            enable_hot_reload=False
        )
        
        sentinel_config = config_manager.get_config('sentinel')
        assert sentinel_config['workspace_id'] == 'test-workspace'

    def test_env_variable_override(self, test_config_path):
        """Test environment variable overrides"""
        os.environ['APP_AWS_REGION'] = 'us-west-2'
        
        config_manager = ConfigManager(
            config_path=str(test_config_path),
            environment="test",
            enable_hot_reload=False
        )
        
        aws_config = config_manager.get_config('aws')
        assert aws_config['region'] == 'us-west-2'

    def test_validation(self, test_config_path):
        """Test configuration validation"""
        # Create invalid config
        invalid_config = {
            'aws': {
                'region': 'us-east-1'
                # Missing required fields
            }
        }
        
        with open(test_config_path / "invalid.yaml", 'w') as f:
            yaml.dump(invalid_config, f)
        
        with pytest.raises(ConfigurationError):
            ConfigManager(
                config_path=str(test_config_path),
                environment="invalid",
                enable_hot_reload=False
            )

    def test_get_aws_config(self, test_config_path):
        """Test getting typed AWS configuration"""
        config_manager = ConfigManager(
            config_path=str(test_config_path),
            environment="test",
            enable_hot_reload=False
        )
        
        aws_config = config_manager.get_aws_config()
        assert aws_config.region == 'us-east-1'
        assert aws_config.bucket_name == 'test-bucket'
        assert aws_config.batch_size == 1000

    def test_get_sentinel_config(self, test_config_path):
        """Test getting typed Sentinel configuration"""
        config_manager = ConfigManager(
            config_path=str(test_config_path),
            environment="test",
            enable_hot_reload=False
        )
        
        sentinel_config = config_manager.get_sentinel_config()
        assert sentinel_config.workspace_id == 'test-workspace'
        assert sentinel_config.retention_days == 90

    @pytest.mark.asyncio
    async def test_reload_config(self, test_config_path):
        """Test configuration reloading"""
        config_manager = ConfigManager(
            config_path=str(test_config_path),
            environment="test",
            enable_hot_reload=True
        )
        
        # Modify config file
        test_config = {
            'aws': {
                'bucket_name': 'updated-bucket'
            }
        }
        
        with open(test_config_path / "test.yaml", 'w') as f:
            yaml.dump(test_config, f)
        
        # Trigger reload
        config_manager.reload_config()
        
        aws_config = config_manager.get_config('aws')
        assert aws_config['bucket_name'] == 'updated-bucket'