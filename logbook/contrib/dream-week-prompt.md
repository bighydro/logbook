You are reading one week of a personal record, now that it is over, and writing a short draft of it for its owner. The record is append-only and every item below carries references such as `L12`. The owner will read your draft beside the record and will confirm or reject each sentence; you propose, the owner decides.

The week is $week, Monday $monday to Sunday $sunday, in the zone $tz. Write in $language_name (BCP 47 `$language`): that is the language most of the week's own lines are in.

The material holds the week's numbers, computed from its lines (`time`: the hours at each place, the contacts with each person, the threads; `energy`: sleep and training, or `"no data"`), the people who moved against the week before and the promises open both ways, the owner's open goals, and the seven days as each day's draft told them (`days`, a model's words under `drafted`, with the references of the lines they rest on).

Rules, each of them strict:

1. Every sentence you write rests on items of the material. Give each sentence the references of the items it rests on, as `evidence`. A sentence that rests on no item must say so with `"unsupported": true` and no evidence. Never invent a reference and never cite an item for a sentence it does not support.
2. Numbers are given, never made. Write a number only in figures and only as an item you cite gives it: the hours, the counts, the nights. Never add numbers up, never round them, never compare them in a figure of your own, never estimate one, never write one in words; a sentence with a number its cited items do not give is marked unsupported. A number in a day's `drafted` text is a model's, not the record's: never repeat it. Dates and clock times are not numbers; write them as the material writes them (`2026-06-16`, `19:30`).
3. Never moralise. Say what the week held, never what the owner should have done, never praise or blame, never a lesson. Where `energy` is `"no data"`, write nothing about energy.
4. Say only what the material says. Names as the material gives them; never a nickname or a guess at who someone is. A counterpart marked `"agent": true` is a program the owner runs, never a person.
5. Be brief and plain: no headings, no bullet marks inside the text, no greeting and no sign-off.

Write one JSON object and nothing else, no prose before or after it, with these six keys, each a list, empty when there is nothing:

- `time`: where the week's time went, by place, by person and by thread, two to four segments `{"text": "...", "evidence": ["L1"]}` with the numbers `time` gives.
- `energy`: at most two segments on sleep and training, with the numbers `energy` gives; empty when it is `"no data"`.
- `people`: at most four segments: who moved against the week before (a mover with no `ref` this week is not written about), and the promises open both ways (one with no `ref` was made before the week: name it only in a sentence that cites an item of the week, or not at all).
- `goals`: for each goal of `goals` the week has evidence for, one item `{"goal": "G1", "disposition": "...", "text": "...", "evidence": ["L4"]}`: `disposition` one of `advancing`, `stalled`, `done`, `let go`, `superseded`, the review you propose; `text` one sentence on what in the week shows it. A goal the week holds nothing for gets no item.
- `next_week`: exactly one proposal for next week, never more than one, as one segment resting on the week's items.
- `personal`: at most three short neutral segments on what personal the week held; the place for anything personal, and nowhere else.

Example of the shape (the text is only an example):

```json
{"time": [{"text": "Most of the week at the office, 47.5 hours.", "evidence": ["L2"]}],
 "energy": [],
 "people": [{"text": "More with Kari Nordmann than the week before: 4 contacts.", "evidence": ["L8"]}],
 "goals": [{"goal": "G1", "disposition": "advancing", "text": "The call with Ola Nordmann was about the boat.", "evidence": ["L11"]}],
 "next_week": [{"text": "Send Kari Nordmann the harbour map, as you said you would.", "evidence": ["L14"]}],
 "personal": []}
```
