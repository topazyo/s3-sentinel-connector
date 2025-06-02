# src/s3_sentinel/cli.py

import argparse

def main():
    parser = argparse.ArgumentParser(description="S3 to Sentinel Connector CLI.")
    parser.add_argument("--config", type=str, help="Path to configuration file.")
    # Add other arguments as the CLI develops
    
    args = parser.parse_args()
    
    print("S3 to Sentinel Connector CLI")
    if args.config:
        print(f"Configuration file specified: {args.config}")
    else:
        print("No configuration file specified. Use --config path/to/config.yaml")
    
    # TODO: Add actual CLI logic here, e.g., initialize ConfigManager, start processing.
    print("CLI is under development.")

if __name__ == '__main__':
    main()
