### Added
- `export share day` shares a day of a sealed record whose lines name an attachment: each sealed
  file is opened with this machine's identity, checked against its name and zipped opened, as the
  lines are; a store file that does not hash to its name, sealed or not, still stops the share (#320).
- `export site` leaves a model's drafts (pencil) out: no Day page or Year pick carries a day's draft,
  its week's or a call's synthesis unless `--with-drafts`, which puts them in headed with their model,
  as the Day page heads them; the owner's reflection follows its own tier as before ([the site](docs/site.md)).
- A voice's name keeps its tier (RFC 0038): the name a reader shows for a voice bound to a person takes
  the highest tier of the lines that give it, and a reading below that tier (a site, a vault, a trip
  bundle, a gated Day) shows `a named voice` in its place and names nobody in its company from that voice.
