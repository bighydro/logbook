### Changed
- Who was there, the owner's answers: `people city CITY --trip ID` takes the journey (`--journey` there
  still works until the release after 1.0, saying once that it is now `--trip`; `--journey` is
  `people nearby`'s alone); `review with --accept N[,N]` takes the queue's numbers like the rest of
  `review`, each printed on a line of its own under the person, and a name there is refused; the
  longest stay a stretch's day is stated at counts its waking hours only, from `day_start` to
  midnight; `review with` refuses every option it does not take, `--since` included
  ([who was there](docs/who-was-there.md)).
