#!/usr/bin/env python3
"""
S3 Sentinel Connector - Data Ingestion Simulator
Pushes synthetic logs to Log Analytics via the Data Collection Rule (DCR) API

Usage:
    python Simulate_Ingest.py \
        --dce-endpoint "https://<dce-name>.ingest.monitor.azure.com" \
        --dcr-rule-id "dcr-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" \
        --stream-name "Custom-Custom_Firewall_CL" \
        --config Simulated_Logs.json

Requirements:
    pip install azure-identity azure-monitor-ingestion
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, cast

try:
    from azure.core.exceptions import HttpResponseError
    from azure.identity import DefaultAzureCredential, InteractiveBrowserCredential
    from azure.monitor.ingestion import LogsIngestionClient
except ImportError:
    print("ERROR: Required packages not installed.")
    print("Run: pip install azure-identity azure-monitor-ingestion")
    sys.exit(1)


class DataCollectorSimulator:
    """Simulate data ingestion to Azure Monitor via DCR"""

    def __init__(self, dce_endpoint: str, dcr_rule_id: str, stream_name: str):
        """
        Initialize the simulator

        Args:
            dce_endpoint: Data Collection Endpoint URL
            dcr_rule_id: Data Collection Rule immutable ID
            stream_name: Stream name (e.g., Custom-Custom_Firewall_CL)
        """
        self.dce_endpoint = dce_endpoint
        self.dcr_rule_id = dcr_rule_id
        self.stream_name = stream_name

        # Initialize Azure credential
        try:
            self.credential = DefaultAzureCredential()
            # Test credential
            self.credential.get_token("https://monitor.azure.com/.default")
            print("✓ Using DefaultAzureCredential")
        except Exception:
            print("⚠ DefaultAzureCredential failed, trying interactive login...")
            self.credential = InteractiveBrowserCredential()

        # Initialize ingestion client
        self.client = LogsIngestionClient(
            endpoint=self.dce_endpoint,
            credential=self.credential,
            logging_enable=True
        )

    def validate_logs(self, logs: List[Dict[str, Any]], schema: Dict[str, Any]) -> List[str]:
        """
        Validate logs against schema

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []
        required_fields = schema.get('required_fields', [])

        for i, log in enumerate(logs):
            for field in required_fields:
                if field not in log or log[field] is None:
                    errors.append(f"Log {i}: Missing required field '{field}'")

            # Validate TimeGenerated format
            if 'TimeGenerated' in log:
                try:
                    datetime.fromisoformat(log['TimeGenerated'].replace('Z', '+00:00'))
                except (ValueError, AttributeError):
                    errors.append(f"Log {i}: Invalid TimeGenerated format")

        return errors

    def send_logs(self, logs: List[Dict[str, Any]], batch_size: int = 100) -> Dict[str, Any]:
        """
        Send logs to Azure Monitor via DCR

        Args:
            logs: List of log dictionaries
            batch_size: Number of logs per batch

        Returns:
            Result dictionary with status and metrics
        """
        results = {
            'total': len(logs),
            'successful': 0,
            'failed': 0,
            'errors': []
        }

        # Ensure TimeGenerated is set
        for log in logs:
            if 'TimeGenerated' not in log:
                log['TimeGenerated'] = datetime.now(timezone.utc).isoformat()

        # Process in batches
        for i in range(0, len(logs), batch_size):
            batch = logs[i:i + batch_size]
            batch_num = i // batch_size + 1

            try:
                # Cast to List[Any] to satisfy the JSON type requirement
                self.client.upload(
                    rule_id=self.dcr_rule_id,
                    stream_name=self.stream_name,
                    logs=cast(List[Any], batch)
                )

                results['successful'] += len(batch)
                print(f"✓ Batch {batch_num}: Ingested {len(batch)} log(s)")

            except HttpResponseError as e:
                results['failed'] += len(batch)
                error_msg = f"Batch {batch_num}: HTTP {e.status_code} - {e.message}"
                results['errors'].append(error_msg)
                print(f"✗ {error_msg}")

            except Exception as e:
                results['failed'] += len(batch)
                error_msg = f"Batch {batch_num}: {e!s}"
                results['errors'].append(error_msg)
                print(f"✗ {error_msg}")

        return results


def load_config(config_path: str) -> Dict[str, Any]:
    """Load simulation configuration from JSON file"""
    with open(config_path, 'r') as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(
        description='Simulate data ingestion for S3 to Sentinel Data Connector'
    )
    parser.add_argument(
        '--dce-endpoint',
        required=True,
        help='Data Collection Endpoint URL (e.g., https://<dce-name>.ingest.monitor.azure.com)'
    )
    parser.add_argument(
        '--dcr-rule-id',
        required=True,
        help='Data Collection Rule immutable ID (e.g., dcr-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx)'
    )
    parser.add_argument(
        '--stream-name',
        required=True,
        help='Stream name (e.g., Custom-Custom_Firewall_CL)'
    )
    parser.add_argument(
        '--config',
        default='Simulated_Logs.json',
        help='Path to simulation config file (default: Simulated_Logs.json)'
    )
    parser.add_argument(
        '--log-type',
        choices=['firewall', 'vpn', 'both'],
        default='firewall',
        help='Type of logs to ingest (default: firewall)'
    )
    parser.add_argument(
        '--include-edge-cases',
        action='store_true',
        help='Include edge case test logs'
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=100,
        help='Number of logs per batch (default: 100)'
    )
    parser.add_argument(
        '--validate-only',
        action='store_true',
        help='Validate logs without sending'
    )

    args = parser.parse_args()

    # Load configuration
    print(f"\n{'='*60}")
    print("S3 Sentinel Connector - Data Ingestion Simulator")
    print(f"{'='*60}\n")

    try:
        config = load_config(args.config)
        print(f"✓ Loaded config from: {args.config}")
    except FileNotFoundError:
        print(f"✗ Config file not found: {args.config}")
        return 1
    except json.JSONDecodeError as e:
        print(f"✗ Invalid JSON in config: {e}")
        return 1

    # Collect logs to send
    logs_to_send = []

    if args.log_type in ['firewall', 'both']:
        logs_to_send.extend(config.get('sampleEvents', []))
        print(f"  - Firewall logs: {len(config.get('sampleEvents', []))}")

    if args.log_type in ['vpn', 'both']:
        logs_to_send.extend(config.get('vpnSampleEvents', []))
        print(f"  - VPN logs: {len(config.get('vpnSampleEvents', []))}")

    if args.include_edge_cases:
        logs_to_send.extend(config.get('edgeCases', []))
        print(f"  - Edge cases: {len(config.get('edgeCases', []))}")

    if not logs_to_send:
        print("✗ No sample events found in config")
        return 1

    print(f"\nTotal logs to process: {len(logs_to_send)}")

    # Validate logs
    schema_key = 'firewall' if args.log_type == 'firewall' else 'vpn'
    schema = config.get('schemaValidation', {}).get(schema_key, {})

    print(f"\n{'='*60}")
    print("Schema Validation")
    print(f"{'='*60}\n")

    # Create simulator
    simulator = DataCollectorSimulator(
        dce_endpoint=args.dce_endpoint,
        dcr_rule_id=args.dcr_rule_id,
        stream_name=args.stream_name
    )

    validation_errors = simulator.validate_logs(logs_to_send, schema)

    if validation_errors:
        print("✗ Validation errors found:")
        for error in validation_errors:
            print(f"  - {error}")
        if not args.validate_only:
            print("\nProceeding with ingestion despite validation warnings...")
    else:
        print("✓ All logs passed schema validation")

    # Exit if validate-only mode
    if args.validate_only:
        print("\n[Validate-only mode - no logs sent]")
        return 0 if not validation_errors else 1

    # Send logs
    print(f"\n{'='*60}")
    print("Ingestion")
    print(f"{'='*60}\n")

    print(f"DCE Endpoint: {args.dce_endpoint}")
    print(f"DCR Rule ID: {args.dcr_rule_id}")
    print(f"Stream Name: {args.stream_name}")
    print(f"Batch Size: {args.batch_size}")
    print()

    results = simulator.send_logs(logs_to_send, batch_size=args.batch_size)

    # Summary
    print(f"\n{'='*60}")
    print("Results Summary")
    print(f"{'='*60}\n")

    print(f"Total logs:      {results['total']}")
    print(f"Successful:      {results['successful']}")
    print(f"Failed:          {results['failed']}")

    if results['errors']:
        print("\nErrors:")
        for error in results['errors']:
            print(f"  - {error}")

    if results['successful'] > 0:
        print(f"\n{'='*60}")
        print("Verification")
        print(f"{'='*60}\n")

        table_name = args.stream_name.replace('Custom-', '')
        print("Run this KQL query in your Log Analytics workspace to verify:")
        print()
        print(f"  {table_name}")
        print("  | where TimeGenerated > ago(1h)")
        print("  | summarize count() by bin(TimeGenerated, 5m)")
        print()
        print("Or check record details:")
        print()
        print(f"  {table_name}")
        print("  | take 10")
        print()

    return 0 if results['failed'] == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
