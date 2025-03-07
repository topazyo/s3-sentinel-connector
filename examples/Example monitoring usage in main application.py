# Example usage in main application

async def main():
    # Initialize pipeline monitor
    monitor = PipelineMonitor(
        metrics_endpoint="https://your-metrics-endpoint",
        app_name="s3-sentinel-connector",
        environment="production"
    )
    
    # Initialize component metrics collectors
    s3_metrics = ComponentMetrics("s3_handler")
    sentinel_metrics = ComponentMetrics("sentinel_router")
    
    # Use in your processing logic
    async def process_batch(batch):
        start_time = time.time()
        try:
            # Process batch
            processed_count = len(batch)
            duration = time.time() - start_time
            
            # Record metrics
            s3_metrics.record_processing(
                count=processed_count,
                duration=duration,
                batch_size=len(batch)
            )
            await monitor.record_metric(
                'logs_processed',
                processed_count,
                {'source': 's3', 'status': 'success'}
            )
            
        except Exception as e:
            s3_metrics.record_error(type(e).__name__)
            await monitor.record_metric(
                'logs_processed',
                0,
                {'source': 's3', 'status': 'error'}
            )
            raise

    # Start monitoring
    await monitor._start_monitoring_tasks()