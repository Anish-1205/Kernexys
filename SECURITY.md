# Security policy

## Supported versions

Kernexys is currently pre-release software. Security fixes are applied only to
the latest commit on the default branch; no released version is supported yet.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability. Use GitHub's private
vulnerability reporting or a private security advisory for this repository and
include:

- the affected component and revision;
- reproduction steps or a minimal proof of concept;
- the impact and required preconditions; and
- any suggested mitigation, if known.

Avoid including real credentials, personal data, or third-party secrets in a
report. Acknowledgement and remediation timelines depend on maintainer
availability while the project remains pre-release.

For non-sensitive hardening suggestions, open a regular GitHub issue. The
current threat model and implemented controls are documented in
[`docs/security.md`](docs/security.md).
