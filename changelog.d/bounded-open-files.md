### Fixed
- `doctor`, `verify` and every reader of the chain hold at most a handful of month files open at
  once, however many the record has: the chain-order merge (`Logbook.lines`), the sorted fallback,
  the index's reads, `migrate`, `seal` and `append_many` each keep a bounded set of handles and reopen
  a file where they left off. A record of a few decades (hundreds of month files) failed `doctor`
  and `verify` on macOS with `[Errno 24] Too many open files` under the default limit of 256.
