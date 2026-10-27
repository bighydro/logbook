### Security

- The MCP write tools `add_note` and `promise_done` are refused unless the `mcp` entry of `policy/crossing.json` names them under `write` and has not expired, as `sign_day` and `note_day` are, and the lines they write have source `mcp`, never `manual`: an agent never writes as the owner.
- A signature never confirms pencil: the dream's draft, a note a model derived (a photo's description, a meeting's summary) and a line an agent wrote through the door are left out of `confirmed` by `day sign`, `day reflect --sign`, the Library's Sign and the door's `sign_day`, and a disposition a standing signature gave one is no longer carried forward.
- `export share day` holds a draft to the entry it was written under, as every other crossing and the MCP door do: a draft whose `dream` entry is missing, lowered under its tier or expired stays home, counted in the manifest's `held_back` and the crossing line's `held_back_by_entry`.
