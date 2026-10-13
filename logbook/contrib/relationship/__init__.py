"""The relationship reader, EXPERIMENTAL (slice 0): one canonical person's lines, read under their own
crossing entry into a disposable derived store, and questions about that person answered from it with
every cited id resolved against the record. README.md beside this file states the boundaries.

`reader` selects the authorized input set (RFC 0036 amendment 1, the person unit) and writes the store
under `state/relationship/<person>/`; `ask` serves it to a model and resolves what the model cites. No
model is wired yet: `ask.MODEL` is None until a later slice wires one, and the tests set a stub. The
reader has no authority over the record: it never appends a line, never signs a day, never writes a note
and never resolves an identity."""
