### Added
- `dream day YYYY-MM-DD [--dry-run] [--show-prompt]`: a model reads one day under the `dream` entry of
  `policy/crossing.json` (`max_tier`, `until`, optional `model`; no entry or an expired one refuses in one
  sentence) and writes one `draft/v1` line (RFC 0036): the day in a paragraph, the threads it moved, two
  questions, the people and promises it proposes, every segment with the ids of the lines it rests on or
  marked unsupported. The model is any OpenAI-compatible chat completions endpoint, `LOGBOOK_DREAM_ENDPOINT`,
  `LOGBOOK_DREAM_MODEL` and, when it needs one, `LOGBOOK_DREAM_KEY`, through one small client with a timeout
  and one retry and no SDK. The material is the Day under the ceiling, messages by counterpart with their
  count and text, notes, commitments and the signing note, never a raw line above the ceiling; the prompt is
  `logbook/contrib/dream-prompt.md` (docs/dream-prompt.md) and says which language to write in, the
  language most of the day's lines are in. An evidence id the day does not have makes the segment
  unsupported; more than 30 % unsupported refuses the answer and nothing is written. The draft's tier is the
  highest tier it read; `read_head` and `read_count` say what it read; dreaming a day again supersedes the
  standing draft; the whole run holds the writer lock and a head that moved is `HeadMoved`, nothing written.
  `dream --catch-up [--days N]` dreams each of the last N days that has no draft or whose lines changed, one
  line per day (docs/dream.md).
- The Day shows the standing draft between the header and the timeline, above every note, headed with the
  model, the head and count it read and `dreamed N×, last on DATE`; an unsupported segment set apart with `~`
  and the word; `day --no-dream` leaves it out and `--json` carries it as `draft`; `serve` shows the same.
  `show` lists a draft line on the day it was written. `doctor` lists the `dream` entry on its `crossing`
  line with the model it names.
