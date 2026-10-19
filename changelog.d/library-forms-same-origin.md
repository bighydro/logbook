### Fixed
- `serve`: every form of the Library (Name this place, Sign, Reflect, Star, With, the review queues,
  the status forms) is answered in a real browser again. The pages were sent with
  `Referrer-Policy: no-referrer`, under which Chrome, Firefox and Safari post a form with
  `Origin: null`, and the write gate refused it (403, nothing written); they are now sent with
  `same-origin`, so a form names its own page's origin and no other site is sent a referrer. The
  gate is as strict as it was.
