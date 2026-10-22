### Added
- The owner's own phone may write through the Library behind Tailscale Serve, off by default:
  `logbook setup phone --origin https://<machine>.<tailnet>.ts.net --login LOGIN` names it in
  `logbook.json` after a yes typed at a terminal, and the Day's Reflect, With, Star and Sign and the
  shelves' forms are then answered from that origin, that Host and that `Tailscale-User-Login` as
  from this machine; a form from any other origin, Host or login is still a 403 with nothing
  written.
  `--off` removes it, and `doctor` says on its `phone` line whether the phone may write and from where
  ([from your phone](docs/serve.md#from-your-phone), ADR 0024).
- A form posted through Tailscale Serve, or any proxy (a `Host` that is not `127.0.0.1` or `[::1]`,
  or a `Tailscale-*` or `X-Forwarded-*` header), is answered only as the phone's: a program on
  another tailnet device that sends no `Origin` is refused, the setting on or off, where before it
  was answered as this machine. Requests to `http://127.0.0.1:8765` or `http://[::1]:8765` from
  this machine are answered as before; one naming any other host, `localhost` included, is treated
  as coming through a proxy.
