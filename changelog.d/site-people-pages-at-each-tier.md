### Fixed
- A fast test checks the site's people pages at tier 1 and at tier 1,2 on a small synthetic
  record: a tier-1 site has a page for the person a tier-1 resolution names and none for one named
  only at tier 2 or 3, and a tier-1,2 site has pages for both the tier-1 and the tier-2 people.
  Before, only the slow forty-year export, which pull requests skip, checked these pages.
