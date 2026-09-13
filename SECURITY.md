# Security

This software stores a person's whole life. Treat every bug as if it were serious.

Report vulnerabilities privately to the address in the repository profile. You will get a reply within 48 hours. Fixes ship before disclosure.

Threat model (v0.1): the logbook lives on a machine the owner controls. The adversary is anyone who obtains the files. Tier 1 is plain; tiers 2 and 3 are encrypted at rest from v0.2 with a key that never leaves the owner's machine. There is no server and no account. Adapters are untrusted code: they run without network by default and can only append.
