# Security

Security fixes target the latest released version. Older versions may not receive
backports; review release notes before updating production workflows.

Report vulnerabilities through [GitHub private vulnerability reporting](https://github.com/amaljithkuttamath/mcdxkit/security/advisories/new).
Include affected versions, a minimal synthetic reproducer, impact and suggested
mitigations. Do not put credentials, client reports or private templates in public
issues. Do not upload client files to a private advisory either without permission
from their owner. There is no guaranteed response time.

Report ordinary calculation or compatibility defects through a sanitized bug
issue. A wrong result is a correctness defect even when it is not a security
vulnerability. If the defect crosses an access boundary or enables resource
exhaustion, use the private reporting channel.

The server is a shared trusted workspace, not a multi-tenant platform. Follow the
[deployment guide](deploy/README.md) before exposing it beyond localhost. Calcpad
execution does not establish Prime-native compatibility or engineering approval.
