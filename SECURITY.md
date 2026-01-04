# Security Policy

If you discover a security vulnerability in this project, please follow these steps:

1. Create a private issue in this repository marked `security` OR contact the maintainer directly.
2. Do not publicly disclose the vulnerability until it has been addressed.
3. Include reproduction steps, affected versions, and any PoC code if available.

Security notes for maintainers and contributors:
- Do not commit secrets or credentials into the repo. Use Key Vault or environment variables for runtime secrets.
- The codebase includes Key Vault usage patterns under `src/security/credential_manager.py` — prefer managed identities in production where available.
- Run static security scanners (e.g., `bandit`) as part of pre-merge checks.

This document is intentionally brief. For sensitive disclosures, contact the repository owner via the private channels listed in the project's governance documents.
