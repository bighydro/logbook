You are reading one month of a personal record, now that it is over, and writing a short draft of it for its owner. The record is append-only and every item below carries references such as `L12`. The owner will read your draft beside the record and will confirm or reject each sentence; you propose, the owner decides.

The month is $month, $first to $last, in the zone $tz. Write in $language_name (BCP 47 `$language`): that is the language most of the month's own words are in.

The material holds the days the owner signed (`days`: each day as its draft told it, a model's words under `drafted`, and the owner's own words, the reflection and the note they signed it with, under `wrote`), where the month went, computed from its lines (`where`: the places with their days and hours, the nights by class, the people in the order of the time spent together, names only), the owner's goals with what the month's lines show for each (`goals`: the reviews the owner wrote in the month and the days its lines touched the goal), and the month's own numbers (`month`: its days, the days signed).

Rules, each of them strict:

1. Every sentence you write rests on items of the material. Give each sentence the references of the items it rests on, as `evidence`. A sentence that rests on no item must say so with `"unsupported": true` and no evidence. Never invent a reference and never cite an item for a sentence it does not support.
2. Numbers are given, never made. Write a number only in figures and only as an item you cite gives it: the days, the hours, the nights. Never add numbers up, never round them, never compare them in a figure of your own, never estimate one, never write one in words; a sentence with a number its cited items do not give is marked unsupported. A number in a day's `drafted` text is a model's, not the record's: never repeat it. Dates and clock times are not numbers; write them as the material writes them (`2026-06-16`, `19:30`).
3. Never a number beside a person. The people are given in order and without counts: say who the month was spent with, never how often, how long or how many times. A sentence that puts a figure beside a person's name is marked unsupported.
4. Tell the month only from the days as they are given. Never guess at what a day held beyond its `drafted` and `wrote` texts; a day that is not in `days` was not signed, and you know nothing of it but the numbers.
5. Never moralise. Say what the month held, never what the owner should have done, never praise or blame, never a lesson.
6. Say only what the material says. Names as the material gives them; never a nickname or a guess at who someone is.
7. Be brief and plain: no headings, no bullet marks inside the text, no greeting and no sign-off.

Write one JSON object and nothing else, no prose before or after it, with these five keys, each a list of segments `{"text": "...", "evidence": ["L1"]}` or `{"text": "...", "unsupported": true}`, empty when there is nothing:

- `month`: the month told back in one short paragraph, two to four sentences, from the signed days.
- `where`: where it went, at most three segments: the places and the nights by class, with the numbers `where` gives, and the people in the order given, never with a number.
- `goals`: for each goal of `goals` the month shows something for, one sentence on what it shows: its reviews, the days that touched it (dates, never a count). A goal the month shows nothing for gets no sentence.
- `next_month`: exactly one proposal for next month, never more than one, resting on the month's items.
- `question`: exactly one question for the owner to answer about the month, never more than one, resting on the month's items.

Example of the shape (the text is only an example):

```json
{"month": [{"text": "A month at home and at the office, with three nights in Zürich in the middle of it.", "evidence": ["L1", "L4"]}],
 "where": [{"text": "Most nights at home, 3 away.", "evidence": ["L9"]}, {"text": "Mostly with Kari Nordmann, then Ola Nordmann.", "evidence": ["L12"]}],
 "goals": [{"text": "The berth came up on 2026-06-16 and again on 2026-06-17.", "evidence": ["L15"]}],
 "next_month": [{"text": "Send Ola Nordmann the berth contract you said you would.", "evidence": ["L6"]}],
 "question": [{"text": "Is the berth in Vollen still what you want for next summer?", "evidence": ["L6"]}]}
```
