# setup.py

from setuptools import setup, find_packages
from typing import List
import os

def read_requirements(filename: str) -> List[str]:
    """Read requirements from file"""
    with open(os.path.join("requirements", filename)) as f:
        return [line.strip() for line in f if line.strip() and not line.startswith("#")]

setup(
    name="s3-sentinel-connector",
    version="1.0.0",
    description="Secure log transfer from AWS S3 to Microsoft Sentinel",
    author="Your Name",
    author_email="your.email@example.com",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    python_requires=">=3.9",
    install_requires=read_requirements("requirements.txt"),
    extras_require={
        "dev": read_requirements("requirements-dev.txt"),
        "test": read_requirements("requirements-test.txt"),
    },
    entry_points={
        "console_scripts": [
            "s3-sentinel=s3_sentinel.cli:main",
        ],
    },
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Information Technology",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Topic :: Security",
        "Topic :: System :: Logging",
    ],
    project_urls={
        "Source": "https://github.com/example-org/s3-sentinel-connector",
        "Documentation": "https://s3-sentinel-connector.readthedocs.io/",
    },
)