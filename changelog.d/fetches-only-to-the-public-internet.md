### Security

- `sync heard` fetches only from the public internet: an address that is not global (the tailnet's 100.64.0.0/10, Tailscale's 100.100.100.100 and a MagicDNS name that resolves into it among them) is refused, the connection goes to the address that was checked and never to a second answer of the resolver, on every redirect, never through a proxy the environment names, and an https page's redirect to http and a port other than 80 and 443 are refused.
- `sync heard` fetches a feed's transcript only under a `heard` entry in `policy/crossing.json`, `{"heard": {"max_tier": 2, "fetch": true}}`: `LOGBOOK_HEARD=feed` alone fetches nothing, the entry is checked before any request, and `doctor` names it.
- `export world` and the Library's `/world` fail closed: a record whose policy names no `world` entry shows tier 1 alone, and `{"world": {"max_tier": 2}}` adds the chapters; `doctor` names it on a `world` line.
- `doctor --packet` sends its probe of the dream endpoint, with the bearer key, only while the policy's `dream` entry allows the dream; with no entry, or one expired, it says the probe was not sent and why. SECURITY.md lists every command that may open a socket.
