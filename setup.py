# setup.py

import os
from typing import List

from setuptools import find_packages, setup


def read_requirements(filename: str) -> List[str]:
    """Read requirements from a top-level requirements file.

    Historically this helper read from a `requirements/` folder. The project
    places `requirements.txt` and `requirements-dev.txt` at the repository
    root — read those files directly to avoid FileNotFoundError.
    """
    path = os.path.join(os.path.dirname(__file__), filename)
    if not os.path.exists(path):
        # Fallback to top-level file name if called with a path fragment
        path = os.path.join(os.path.dirname(__file__), os.pardir, filename)
        path = os.path.normpath(path)

    with open(path, "r", encoding="utf-8") as f:
        return [
            line.strip()
            for line in f
            if line.strip() and not line.strip().startswith("#")
        ]


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
        "Source": "https://github.com/yourusername/s3-sentinel-connector",
        "Documentation": "https://s3-sentinel-connector.readthedocs.io/",
    },
)
