# Security policy

Report vulnerabilities privately through GitHub private vulnerability reporting. Do not open a public issue containing webhook secrets, private keys, installation tokens, or exploit details.

The service must be deployed over HTTPS. Store the GitHub App private key and webhook secret in a secrets manager, grant only the documented GitHub permissions, rotate compromised credentials, and review logs for accidental sensitive-data capture.

Repository files are retrieved only for the requested audit. Operators are responsible for defining retention, logging, access-control, and privacy policies appropriate to their deployment.
