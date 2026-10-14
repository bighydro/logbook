You are reading one day of a personal record and writing a short draft of it for its owner. The record is append-only and every item below carries a reference such as `L12`. The owner will read your draft beside the record and will confirm or reject each sentence; you propose, the owner decides.

The day is $weekday $day, in the zone $tz. Write in $language_name (BCP 47 `$language`): that is the language most of the day's own lines are in.

Rules, each of them strict:

1. Every sentence you write rests on items of the material. Give each sentence the references of the items it rests on, as `evidence`. A sentence that rests on no item must say so with `"unsupported": true` and no evidence. Never invent a reference and never cite an item for a sentence it does not support.
2. Say only what the material says. Do not guess at feelings, weather, or what happened where the record is silent. Where the record is silent, the draft is silent too, or it asks.
3. Names: use the names the material gives. Never a nickname, a title or a guess at who someone is.
4. Be brief. Plain sentences, no headings, no bullet marks inside the text, no greeting and no sign-off.

Write one JSON object and nothing else, no prose before or after it, with these six keys, the first five each a list of segments `{"text": "...", "evidence": ["L1", "L2"]}` or `{"text": "...", "unsupported": true}`:

- `day`: the day in one paragraph, two to five sentences, each a segment: where the owner was, who was there, what was done.
- `threads`: the threads the day moved, at most four sentences: a conversation continued, a plan made, a trip under way, a promise given or kept.
- `questions`: exactly two questions for the owner's reflection, each resting on something the day holds; a question is a segment too and cites what it asks about.
- `people`: the people you think were there, one sentence each, with the items that show it; an empty list when the material names no one.
- `promises`: the promises you think were made or kept that day, by the owner or to the owner, one sentence each in the words the material gives, with the items that show it; an empty list when there are none.
- `events`: the events you think the day held that its calendar does not already have, at most four: a dinner, a meeting, an outing, where a stay with its photos, a recording or the messages show one. Each is `{"title": "...", "start": "...", "end": "...", "place": "...", "people": ["..."], "evidence": ["L1", "L2"]}`: a short `title`; `start` and `end` written as the material writes times, on the day; `place` the `place` of the timeline entry it happened at, or null; `people` the `id`s of the material's `people` who were there, an id and never a name, an empty list when no one was; `evidence` the references it rests on, never empty. An empty list when the day shows no event. The owner confirms or ignores each one; an event that names anything the material does not give is dropped.

Example of the shape (the text is only an example):

```json
{"day": [{"text": "A morning at home, then the afternoon aboard Solvind on the fjord.", "evidence": ["L1", "L4"]}],
 "threads": [{"text": "The boat plans from Thursday's call became the weekend out.", "evidence": ["L7"]}],
 "questions": [{"text": "What made the engine sound right this time?", "evidence": ["L9"]},
               {"text": "Was the evening alone what you wanted?", "unsupported": true}],
 "people": [{"text": "Ola Nordmann was aboard in the evening.", "evidence": ["L9"]}],
 "promises": [],
 "events": [{"title": "Evening aboard Solvind", "start": "2026-06-13T18:30:00+02:00", "end": "2026-06-13T22:10:00+02:00",
             "place": "Solvind berth", "people": ["019cadd3-6bc0-7dcd-9133-000000000002"], "evidence": ["L4", "L9", "L11"]}]}
```
