# Conformance

`sample-logbook/` is one week of a fictional person (Oslo, March 2026). Nothing in it is real.

Your implementation is conformant with format v0.2 when:

1. `verify` on `sample-logbook/` reports **valid** and prints the `seq` and `head` in `expected.json`;
2. appending one line to a copy of it yields a logbook that still verifies, with `seq + 1`;
3. editing any byte inside any line's content, or deleting any line, makes `verify` fail.

Regenerate with `python conformance/make_sample.py` (only when the spec changes; it changes the head).
