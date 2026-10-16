### Changed
- `doctor` checks five extras: `extra:speakers` joins `ais`, `crypto`, `sealed` and `transcribe`, a pass
  when pyannote.audio is installed and a warn with `pip install "openlogbook[speakers]"` when not. It is
  asked by the installed distribution, so neither pyannote nor torch is imported to find out. A machine
  with `[transcribe]` and without `[speakers]` now has that one warn
  ([the doctor](docs/doctor.md#the-extras)).
- The `notion` entry's example in [export for Notion](docs/export-notion.md) has no `write` key, as the
  refusal that names the entry has none: left out, `write` is the empty list it must stay, and an entry
  that spells out `"write": []` is read the same.
