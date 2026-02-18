# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in Work-Flow, please report it responsibly.

**Do NOT open a public GitHub issue for security vulnerabilities.**

Instead, please email: **security@work-flow.dev** (placeholder — update before public release)

### What to Include

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

### Response Timeline

- **Acknowledgment**: Within 48 hours
- **Initial assessment**: Within 1 week
- **Fix & disclosure**: Coordinated with reporter

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes       |

## Security Considerations

This platform integrates with external services (Claude CLI, Figma API, Jira API). Users should:

- Never commit API keys or tokens to the repository
- Use `.env` files for sensitive configuration (included in `.gitignore`)
- Review generated code before merging to production
- Run the platform in trusted environments only
