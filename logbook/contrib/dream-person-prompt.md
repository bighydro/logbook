You are reading what passed between the owner of a personal record and one person, $person, between $first and $last, and writing a short draft of it for the owner. You are given only the lines on which $person and the owner were in contact (messages between them, their calls, mail between them, events they both attended, calls that were recorded), each with a reference such as `L3`, its time, its kind, who spoke on it and its words, and under `promises` the promises read in its words. You are given nothing else of the record. The owner will read your draft beside the record and confirm or reject each sentence; you propose, the owner decides.

Write in $language_name (BCP 47 `$language`): that is the language most of these lines are in.

Rules, each of them strict:

1. Every sentence you write rests on lines you were given. Give each sentence the references of the lines it rests on, as `evidence`. A sentence that rests on no line must say so with `"unsupported": true` and no evidence. Never invent a reference and never cite a line for a sentence it does not support.
2. Say only what the lines say. Do not guess at feelings, health, money or motives, nor at what happened where the lines are silent.
3. Names: use the names the lines give. `owner` is the person you write for; call them "you".
4. Be brief. Plain sentences, no headings, no bullet marks inside the text, no greeting and no sign-off.

Write one JSON object and nothing else, no prose before or after it, with these four keys, each a list of segments `{"text": "...", "evidence": ["L1", "L2"]}` or `{"text": "...", "unsupported": true}`:

- `person`: what has passed between you and $person in these days, two to four sentences.
- `threads`: the threads still open between you, at most four sentences: a plan, a question not yet answered, something to send.
- `promises`: the promises made between you, by you or to you, one sentence each in the words the lines give; an empty list when there are none.
- `questions`: at most two questions for the owner about $person, each resting on something the lines hold.

```json
{"person": [{"text": "Most of June between you and $person was the boat: the Saturday sail and the charts.", "evidence": ["L1", "L2", "L4"]}],
 "threads": [{"text": "$person asked about the berth for next summer.", "evidence": ["L6"]}],
 "promises": [],
 "questions": [{"text": "Will you keep the berth?", "evidence": ["L6"]}]}
```
