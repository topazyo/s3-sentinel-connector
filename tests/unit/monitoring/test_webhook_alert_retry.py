"""
Tests for webhook alert retry logic (B2-007 completion)

Phase 4 (B2-007/P2-RES-01): Test retry logic with exponential backoff for Teams/Slack webhooks
- Retry on 5xx errors (server errors)
- Retry on network failures (ClientError, TimeoutError)
- Don't retry on 4xx errors (client errors)
- Exponential backoff: 1s, 2s, 4s
- 3 total attempts max
- 5s timeout per attempt

Author: VIBE Phase 10 Implementation
Date: 2026-01-03
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, call
from datetime import datetime, timezone

from src.monitoring.pipeline_monitor import PipelineMonitor, AlertConfig


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def alert_data():
    """Sample alert data for testing"""
    return {
        'name': 'test_alert',
        'severity': 'high',
        'threshold': 100,
        'current_value': 150,
        'environment': 'test',
        'description': 'Test alert description'
    }


@pytest.fixture
def mock_pipeline_monitor():
    """Mock PipelineMonitor with webhook configured"""
    # Mock Azure Monitor dependencies to avoid ImportError
    with patch('src.monitoring.pipeline_monitor.MetricsIngestionClient'), \
         patch('src.monitoring.pipeline_monitor.DefaultAzureCredential'):
        
        monitor = PipelineMonitor(
            metrics_endpoint='http://localhost:9090',
            app_name='test-app',
            environment='test',
            teams_webhook='https://teams.webhook.test/hook',
            slack_webhook='https://slack.webhook.test/hook',
            health_timeout=5.0
        )
        return monitor


# ============================================================================
# MOCK RESPONSE CLASSES
# ============================================================================

class MockResponse:
    """Mock aiohttp response"""
    def __init__(self, status: int, text: str = ""):
        self.status = status
        self._text = text
    
    async def text(self):
        return self._text
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return False


class MockSession:
    """Mock aiohttp session"""
    def __init__(self, responses):
        """
        Args:
            responses: List of responses (status codes or exceptions) to return on each call
        """
        self.responses = responses
        self.call_count = 0
        self.post_calls = []
    
    def post(self, url, json=None):
        """Mock post method"""
        self.post_calls.append({'url': url, 'json': json})
        
        if self.call_count < len(self.responses):
            response = self.responses[self.call_count]
            self.call_count += 1
            
            # If response is an exception, raise it
            if isinstance(response, Exception):
                raise response
            
            # If response is an int, return MockResponse with that status
            return MockResponse(response)
        
        # Default to 200 if no more responses
        return MockResponse(200)
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return False


# ============================================================================
# TEST CLASS: Teams Webhook Retry Logic
# ============================================================================

class TestTeamsWebhookRetry:
    """Test Teams webhook retry logic with exponential backoff"""
    
    @pytest.mark.asyncio
    async def test_teams_alert_success_first_attempt(self, mock_pipeline_monitor, alert_data):
        """Test Teams alert succeeds on first attempt (no retry needed)"""
        # Arrange
        mock_session = MockSession([200])  # Success on first try
        
        with patch('aiohttp.ClientSession', return_value=mock_session):
            # Act
            await mock_pipeline_monitor._send_teams_alert(alert_data)
            
            # Assert
            assert mock_session.call_count == 1, "Should only make 1 attempt"
            assert len(mock_session.post_calls) == 1, "Should only call post once"
    
    @pytest.mark.asyncio
    async def test_teams_alert_retries_on_500_error(self, mock_pipeline_monitor, alert_data):
        """Test Teams alert retries on 500 server error"""
        # Arrange
        mock_session = MockSession([500, 500, 200])  # Fail twice, succeed third
        
        with patch('aiohttp.ClientSession', return_value=mock_session):
            # Act
            await mock_pipeline_monitor._send_teams_alert(alert_data)
            
            # Assert
            assert mock_session.call_count == 3, "Should make 3 attempts"
            assert len(mock_session.post_calls) == 3, "Should call post 3 times"
    
    @pytest.mark.asyncio
    async def test_teams_alert_retries_on_503_error(self, mock_pipeline_monitor, alert_data):
        """Test Teams alert retries on 503 service unavailable"""
        # Arrange
        mock_session = MockSession([503, 200])  # Fail once, succeed second
        
        with patch('aiohttp.ClientSession', return_value=mock_session):
            # Act
            await mock_pipeline_monitor._send_teams_alert(alert_data)
            
            # Assert
            assert mock_session.call_count == 2, "Should make 2 attempts"
    
    @pytest.mark.asyncio
    async def test_teams_alert_no_retry_on_400_error(self, mock_pipeline_monitor, alert_data):
        """Test Teams alert doesn't retry on 400 client error"""
        # Arrange
        mock_session = MockSession([400])  # Client error (don't retry)
        
        with patch('aiohttp.ClientSession', return_value=mock_session):
            # Act
            await mock_pipeline_monitor._send_teams_alert(alert_data)
            
            # Assert
            assert mock_session.call_count == 1, "Should only make 1 attempt (no retry on 4xx)"
    
    @pytest.mark.asyncio
    async def test_teams_alert_no_retry_on_404_error(self, mock_pipeline_monitor, alert_data):
        """Test Teams alert doesn't retry on 404 not found"""
        # Arrange
        mock_session = MockSession([404])  # Not found (don't retry)
        
        with patch('aiohttp.ClientSession', return_value=mock_session):
            # Act
            await mock_pipeline_monitor._send_teams_alert(alert_data)
            
            # Assert
            assert mock_session.call_count == 1, "Should only make 1 attempt (no retry on 4xx)"
    
    @pytest.mark.asyncio
    async def test_teams_alert_exhausts_retries(self, mock_pipeline_monitor, alert_data, caplog):
        """Test Teams alert exhausts all 3 retries on persistent 500 error"""
        # Arrange
        mock_session = MockSession([500, 500, 500])  # All attempts fail
        
        with patch('aiohttp.ClientSession', return_value=mock_session):
            # Act
            await mock_pipeline_monitor._send_teams_alert(alert_data)
            
            # Assert
            assert mock_session.call_count == 3, "Should make exactly 3 attempts"
            assert "failed after 3 attempts" in caplog.text, "Should log exhaustion message"
    
    @pytest.mark.asyncio
    async def test_teams_alert_retries_on_network_error(self, mock_pipeline_monitor, alert_data):
        """Test Teams alert retries on network error (ClientError)"""
        # Arrange
        import aiohttp
        mock_session = MockSession([
            aiohttp.ClientError("Network error"),
            200  # Success on retry
        ])
        
        with patch('aiohttp.ClientSession', return_value=mock_session):
            # Act
            await mock_pipeline_monitor._send_teams_alert(alert_data)
            
            # Assert
            assert mock_session.call_count == 2, "Should retry after network error"
    
    @pytest.mark.asyncio
    async def test_teams_alert_retries_on_timeout(self, mock_pipeline_monitor, alert_data):
        """Test Teams alert retries on timeout error"""
        # Arrange
        mock_session = MockSession([
            asyncio.TimeoutError("Request timeout"),
            200  # Success on retry
        ])
        
        with patch('aiohttp.ClientSession', return_value=mock_session):
            # Act
            await mock_pipeline_monitor._send_teams_alert(alert_data)
            
            # Assert
            assert mock_session.call_count == 2, "Should retry after timeout"
    
    @pytest.mark.asyncio
    @patch('asyncio.sleep', new_callable=AsyncMock)
    async def test_teams_alert_exponential_backoff(self, mock_sleep, mock_pipeline_monitor, alert_data):
        """Test Teams alert uses exponential backoff (1s, 2s, 4s)"""
        # Arrange
        mock_session = MockSession([500, 500, 500])  # All fail to test full backoff
        
        with patch('aiohttp.ClientSession', return_value=mock_session):
            # Act
            await mock_pipeline_monitor._send_teams_alert(alert_data)
            
            # Assert
            assert mock_sleep.call_count == 2, "Should sleep 2 times (between 3 attempts)"
            # Verify exponential backoff: 1s, 2s
            mock_sleep.assert_has_calls([call(1), call(2)], any_order=False)
    
    @pytest.mark.asyncio
    async def test_teams_alert_skips_if_no_webhook(self, alert_data):
        """Test Teams alert skips gracefully if webhook not configured"""
        # Arrange
        with patch('src.monitoring.pipeline_monitor.MetricsIngestionClient'), \
             patch('src.monitoring.pipeline_monitor.DefaultAzureCredential'):
            
            monitor = PipelineMonitor(
                metrics_endpoint='http://localhost:9090',
                app_name='test-app',
                environment='test',
                teams_webhook=None  # No webhook configured
            )
            
            # Act - should not raise
            await monitor._send_teams_alert(alert_data)
            
            # Assert - no exception raised
            assert True, "Should handle missing webhook gracefully"


# ============================================================================
# TEST CLASS: Slack Webhook Retry Logic
# ============================================================================

class TestSlackWebhookRetry:
    """Test Slack webhook retry logic with exponential backoff"""
    
    @pytest.mark.asyncio
    async def test_slack_alert_success_first_attempt(self, mock_pipeline_monitor, alert_data):
        """Test Slack alert succeeds on first attempt (no retry needed)"""
        # Arrange
        mock_session = MockSession([200])  # Success on first try
        
        with patch('aiohttp.ClientSession', return_value=mock_session):
            # Act
            await mock_pipeline_monitor._send_slack_alert(alert_data)
            
            # Assert
            assert mock_session.call_count == 1, "Should only make 1 attempt"
    
    @pytest.mark.asyncio
    async def test_slack_alert_retries_on_500_error(self, mock_pipeline_monitor, alert_data):
        """Test Slack alert retries on 500 server error"""
        # Arrange
        mock_session = MockSession([500, 500, 200])  # Fail twice, succeed third
        
        with patch('aiohttp.ClientSession', return_value=mock_session):
            # Act
            await mock_pipeline_monitor._send_slack_alert(alert_data)
            
            # Assert
            assert mock_session.call_count == 3, "Should make 3 attempts"
    
    @pytest.mark.asyncio
    async def test_slack_alert_retries_on_502_error(self, mock_pipeline_monitor, alert_data):
        """Test Slack alert retries on 502 bad gateway"""
        # Arrange
        mock_session = MockSession([502, 200])  # Fail once, succeed second
        
        with patch('aiohttp.ClientSession', return_value=mock_session):
            # Act
            await mock_pipeline_monitor._send_slack_alert(alert_data)
            
            # Assert
            assert mock_session.call_count == 2, "Should make 2 attempts"
    
    @pytest.mark.asyncio
    async def test_slack_alert_no_retry_on_400_error(self, mock_pipeline_monitor, alert_data):
        """Test Slack alert doesn't retry on 400 client error"""
        # Arrange
        mock_session = MockSession([400])  # Client error (don't retry)
        
        with patch('aiohttp.ClientSession', return_value=mock_session):
            # Act
            await mock_pipeline_monitor._send_slack_alert(alert_data)
            
            # Assert
            assert mock_session.call_count == 1, "Should only make 1 attempt (no retry on 4xx)"
    
    @pytest.mark.asyncio
    async def test_slack_alert_no_retry_on_429_error(self, mock_pipeline_monitor, alert_data):
        """Test Slack alert doesn't retry on 429 rate limit (client error)"""
        # Arrange
        mock_session = MockSession([429])  # Rate limit (don't retry - client should back off)
        
        with patch('aiohttp.ClientSession', return_value=mock_session):
            # Act
            await mock_pipeline_monitor._send_slack_alert(alert_data)
            
            # Assert
            assert mock_session.call_count == 1, "Should only make 1 attempt (no retry on 4xx)"
    
    @pytest.mark.asyncio
    async def test_slack_alert_exhausts_retries(self, mock_pipeline_monitor, alert_data, caplog):
        """Test Slack alert exhausts all 3 retries on persistent 500 error"""
        # Arrange
        mock_session = MockSession([500, 500, 500])  # All attempts fail
        
        with patch('aiohttp.ClientSession', return_value=mock_session):
            # Act
            await mock_pipeline_monitor._send_slack_alert(alert_data)
            
            # Assert
            assert mock_session.call_count == 3, "Should make exactly 3 attempts"
            assert "failed after 3 attempts" in caplog.text, "Should log exhaustion message"
    
    @pytest.mark.asyncio
    async def test_slack_alert_retries_on_network_error(self, mock_pipeline_monitor, alert_data):
        """Test Slack alert retries on network error (ClientError)"""
        # Arrange
        import aiohttp
        mock_session = MockSession([
            aiohttp.ClientError("Connection reset"),
            200  # Success on retry
        ])
        
        with patch('aiohttp.ClientSession', return_value=mock_session):
            # Act
            await mock_pipeline_monitor._send_slack_alert(alert_data)
            
            # Assert
            assert mock_session.call_count == 2, "Should retry after network error"
    
    @pytest.mark.asyncio
    async def test_slack_alert_retries_on_timeout(self, mock_pipeline_monitor, alert_data):
        """Test Slack alert retries on timeout error"""
        # Arrange
        mock_session = MockSession([
            asyncio.TimeoutError("Request timeout"),
            200  # Success on retry
        ])
        
        with patch('aiohttp.ClientSession', return_value=mock_session):
            # Act
            await mock_pipeline_monitor._send_slack_alert(alert_data)
            
            # Assert
            assert mock_session.call_count == 2, "Should retry after timeout"
    
    @pytest.mark.asyncio
    @patch('asyncio.sleep', new_callable=AsyncMock)
    async def test_slack_alert_exponential_backoff(self, mock_sleep, mock_pipeline_monitor, alert_data):
        """Test Slack alert uses exponential backoff (1s, 2s, 4s)"""
        # Arrange
        mock_session = MockSession([500, 500, 500])  # All fail to test full backoff
        
        with patch('aiohttp.ClientSession', return_value=mock_session):
            # Act
            await mock_pipeline_monitor._send_slack_alert(alert_data)
            
            # Assert
            assert mock_sleep.call_count == 2, "Should sleep 2 times (between 3 attempts)"
            # Verify exponential backoff: 1s, 2s
            mock_sleep.assert_has_calls([call(1), call(2)], any_order=False)
    
    @pytest.mark.asyncio
    async def test_slack_alert_skips_if_no_webhook(self, alert_data):
        """Test Slack alert skips gracefully if webhook not configured"""
        # Arrange
        with patch('src.monitoring.pipeline_monitor.MetricsIngestionClient'), \
             patch('src.monitoring.pipeline_monitor.DefaultAzureCredential'):
            
            monitor = PipelineMonitor(
                metrics_endpoint='http://localhost:9090',
                app_name='test-app',
                environment='test',
                slack_webhook=None  # No webhook configured
            )
            
            # Act - should not raise
            await monitor._send_slack_alert(alert_data)
            
            # Assert - no exception raised
            assert True, "Should handle missing webhook gracefully"


# ============================================================================
# TEST CLASS: Retry Logic Integration
# ============================================================================

class TestWebhookRetryIntegration:
    """Integration tests for webhook retry logic"""
    
    @pytest.mark.asyncio
    async def test_teams_and_slack_both_retry_independently(self, alert_data):
        """Test Teams and Slack retry independently"""
        # Arrange
        with patch('src.monitoring.pipeline_monitor.MetricsIngestionClient'), \
             patch('src.monitoring.pipeline_monitor.DefaultAzureCredential'):
            
            monitor = PipelineMonitor(
                metrics_endpoint='http://localhost:9090',
                app_name='test-app',
                environment='test',
                teams_webhook='https://teams.webhook.test/hook',
                slack_webhook='https://slack.webhook.test/hook'
            )
            
            teams_session = MockSession([500, 200])  # Teams: fail once, succeed
            slack_session = MockSession([500, 500, 200])  # Slack: fail twice, succeed
            
            # Each retry creates a new ClientSession, so return the same mock session
            # for all attempts of each webhook
            # Teams will make 2 attempts (2 sessions), Slack will make 3 attempts (3 sessions)
            sessions = [teams_session, teams_session, slack_session, slack_session, slack_session]
            session_iter = iter(sessions)
            
            # Act
            with patch('aiohttp.ClientSession', side_effect=lambda **kwargs: next(session_iter)):
                await monitor._send_teams_alert(alert_data)
                await monitor._send_slack_alert(alert_data)
            
            # Assert
            assert teams_session.call_count == 2, "Teams should make 2 attempts"
            assert slack_session.call_count == 3, "Slack should make 3 attempts"
    
    @pytest.mark.asyncio
    async def test_webhook_retry_respects_timeout(self, mock_pipeline_monitor, alert_data):
        """Test webhook retry respects configured timeout (5s per attempt)"""
        # Arrange - timeout should be enforced per attempt
        # This test verifies ClientSession is created with timeout config
        
        with patch('aiohttp.ClientSession') as mock_client_session:
            mock_session = MockSession([200])
            mock_client_session.return_value = mock_session
            
            # Act
            await mock_pipeline_monitor._send_teams_alert(alert_data)
            
            # Assert - ClientSession created with timeout
            mock_client_session.assert_called()
            call_kwargs = mock_client_session.call_args[1]
            assert 'timeout' in call_kwargs, "Should pass timeout to ClientSession"
            # Timeout object should have total=5.0 (health_timeout)
            assert call_kwargs['timeout'].total == 5.0, "Timeout should be 5.0 seconds"
