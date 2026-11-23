# Security Policy

## Reporting a Vulnerability

Report a suspected vulnerability through [GitHub's private vulnerability
reporting form](https://github.com/emiluzelac/alethic/security/advisories/new).

Please do not open a public issue for a security vulnerability.

We aim to acknowledge a report within 72 hours and to keep you updated as we
work on a fix. If you would like credit in the release notes, say so in your
report.

## Supported Versions

Alethic is pre-1.0. Only the latest release receives security fixes.

| Version | Supported |
| ------- | --------- |
| 0.4.0   | ✅        |

## Scope and Known Limitations

Alethic is a governance layer, so it is worth being precise about what it does
and does not currently defend against. The following are **known** and are not
useful as vulnerability reports — though better ideas for fixing them are very
welcome, as issues or pull requests.

### The permissions matrix is worker discipline, not a security boundary

In-process, the role is declared by the caller. The matrix keeps a well-behaved
worker in its lane; it does not defend against code that lies about its role.
Only give kernel access to code you trust.

### The library's threat model

The library assumes a **trusted integrator** and an **untrusted model**. That
second half is the part Alethic is built to handle: planner output is proposed
to the kernel and must pass its validation pipeline before commitment. Alethic
does not authenticate callers or prevent trusted application code from bypassing
the kernel entirely.

**A way to defeat that is exactly what we want to hear about.** If you can make
the kernel commit a belief, action, or prediction that its validation pipeline
should have rejected — through model output, evidence handling, TTL or
confidence edge cases, or constraint evaluation — please report it. That is the
core guarantee, and a bypass is a real vulnerability regardless of how contrived
the setup looks.
