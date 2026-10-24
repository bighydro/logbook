### Adapters
- `add beeper` and `sync beeper` mark your own bots as machine text, as the Telegram adapters do: a line a
  named sender wrote carries `extra.machine`, every line of a one-on-one chat with one `extra.counterpart`
  of kind `agent`, so no reader takes the bot for a person. The senders are yours to name, never in the
  code: `logbook setup agents list|add SENDER [--name NAME]|remove SENDER` keeps them in
  `policy/agents.json` ([your own agents](docs/adapters/agents.md#your-bots-through-beeper)).
- `logbook doctor` has an `agents` line: the lines marked machine, per source, and the senders named.
