# S3 to Sentinel Log Connector

A high-performance, secure connector for transferring logs from AWS S3 to Microsoft Sentinel.

## Features
- Real-time log transfer from S3 to Sentinel
- Multi-format log parsing support
- Secure credential management
- Comprehensive monitoring and alerting
- Production-grade error handling

## Installation

```bash
# Clone the repository
git clone https://github.com/example-org/s3-sentinel-connector.git
cd s3-sentinel-connector

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or
.\venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements/requirements.txt

# For development (including linters, testing tools, and compliance checks)
pip install -r requirements/requirements-dev.txt
pip install -r requirements/requirements-test.txt
```

## Usage

### Command-Line Interface (CLI)
The project provides a CLI for main operations. After installation (which registers the `s3-sentinel` command), you can use it as follows:

```bash
# Example: Show help message (once implemented in src/s3_sentinel/cli.py)
s3-sentinel --help

# Example: Run with a specific configuration (once implemented)
s3-sentinel --config config/prod.yaml
```

### Basic usage example:
```python
from src.core.s3_handler import S3Handler
from src.core.sentinel_router import SentinelRouter

# Initialize handlers
s3_handler = S3Handler(aws_access_key, aws_secret_key, region)
sentinel_router = SentinelRouter()

# Process logs
objects = s3_handler.list_objects(bucket_name, prefix)
s3_handler.process_files_batch(bucket_name, objects)
```

## Configuration

Create a `.env` file with your credentials:
```
AWS_ACCESS_KEY=your_access_key
AWS_SECRET_KEY=your_secret_key
AZURE_TENANT_ID=your_tenant_id
```

## Testing
```bash
pytest tests/
```

## Contributing
Please read [CONTRIBUTING.md](CONTRIBUTING.md) for details on our code of conduct and the process for submitting pull requests.

## License
This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.