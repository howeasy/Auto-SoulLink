# Triage labels

The five canonical roles, each label string equal to its name. Unchanged from the defaults, so a
skill needs no per-repo mapping.

| Label | Means | Next actor |
|---|---|---|
| `needs-triage` | Arrived raw; nobody has judged it yet. | whoever triages |
| `needs-info` | Cannot be acted on as written — a repro, a path, or a decision is missing. | the reporter |
| `ready-for-agent` | Self-contained enough that an agent can implement it without this conversation. | an implementation lane |
| `ready-for-human` | Needs a person: a judgement call, a credential, a dashboard, a physical cartridge. | the owner |
| `wontfix` | Deliberately not doing it. Keeps the reasoning so it is not re-proposed. | nobody |

## How they are applied here

Issues are local markdown (`docs/agents/issue-tracker.md`), so a "label" is a line in the ticket
rather than tracker metadata:

```markdown
**Status (2026-09-26):** ready-for-agent — <what proves it is ready>
```

## What triage is and is not for

`triage` is for issues **you did not create**: a bug report, an incoming request, anything that
arrives raw. Tickets produced by `to-tickets` are already agent-ready by construction — triaging
them is busywork.

`ready-for-agent` is a claim that the ticket is self-contained. If an agent would have to ask a
question to start, it is `needs-info`, whatever else is written in it.

`ready-for-human` is the honest label for most of this repo's blocking work: owner gate
signatures, physical cartridge runs, and anything needing a real emulator lane. Do not label those
`ready-for-agent` because an agent could technically start them.
