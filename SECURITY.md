# Security Policy

## Reporting Security Issues

Do **not** open a public issue for security vulnerabilities. Instead, email security@masterprodev.com with:

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

## Security Commitments

This project follows these practices:

- **No secrets in code or images**: All credentials use environment variables and Railway secrets
- **Secret scanning**: Pre-commit hooks and CI prevent key leaks
- **Authentication required**: All side-effect tools require verified user identity
- **PII protection**: Personal data is pseudonymized by default; third-party LLMs receive tokens only
- **Dependency auditing**: Regular checks for known vulnerabilities
- **Signed commits**: Git commits are signed with contributor keys

## Deployment Security

Production deployments must:

1. Use Railway Pro with private networking
2. Enable all CI quality gates (lint, type check, tests, secret scan)
3. Rotate API keys and secrets on a schedule
4. Maintain backups and test disaster recovery annually
5. Run the security compliance checklist before launch

See docs/SECURITY.md and runbooks/ for detailed guidance.
