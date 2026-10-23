### Changed
- `export share day` refuses a day that holds sealed lines (a tier-2 or tier-3 line of a record with
  recipients, at a tier the page would send), in one sentence and before anything is written: the page
  carried them opened, and the receiver's `import page` refused it because their hashes cover the sealed
  reference. A sealed day shares after v1, when a page can carry sealed lines to the receiver (RFC 0029);
  a day whose only sealed thing is an attachment still shares, its file opened as before (#364).
