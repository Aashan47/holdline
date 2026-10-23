# Security policy

## Supported versions

Security fixes go into the latest minor release on PyPI. Please upgrade before reporting.

## Reporting a vulnerability

Please report privately, not in a public issue:

- Use **Report a vulnerability** on the repository's Security tab (GitHub private vulnerability
  reporting), or
- email aashanjaved567@gmail.com with "holdline security" in the subject.

Include the holdline version, what an attacker could do, and steps or a file that reproduce it. You'll
get an acknowledgement within a week, and a fix or a plan once the problem is confirmed. Credit is
given in the release notes unless you'd rather stay anonymous.

## Scope notes

- holdline runs agent code and custom checks that you point it at; it does not sandbox them. Only run
  suites and targets you trust.
- HTML reports and the browser judge check make no network requests. A report that loads a remote
  resource, or a way to make the judge check send data anywhere, is a security bug.
