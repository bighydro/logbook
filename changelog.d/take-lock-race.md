### Fixed
- A writer waiting for `state/writer.lock` no longer dies with `FileNotFoundError` when the holder's release
  removes `state/` between the waiter's making the folder and creating the lock: it makes the folder again and
  tries again under the same rules, so a lock another writer took in the meantime is still waited for, or
  refused under `--no-wait`. Seen once on Windows CI.
