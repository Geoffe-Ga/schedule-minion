# Schedule Minion

> A Discord bot that protects invisible labor by giving a family a shared calendar
> they can add to in plain English.

## Mission

Most household coordination — the doctor's appointments, the carpool swap, the
"don't forget Layla has dance Thursday" — is **invisible labor**. It rarely
shows up on a to-do list, it almost never gets credit, and it almost always
falls on one person.

Schedule Minion is a small attempt to make that work visible and shareable.
Anyone in the family — kid, parent, the parent who handles "everything else" —
can drop a sentence into a Discord channel and the calendar updates for
everybody. No app to learn. No form to fill. No "I thought *you* were going
to put it on the calendar."

The bot does the boring part. The mental load gets distributed instead of
hoarded.

## What It Does

Users mention `@Schedule Minion` in the family `#schedule` channel and talk
to it like a person. It handles four scheduling intents and one scheduled
broadcast:

| Intent | Example | Behavior |
|---|---|---|
| **Create** | *"Dinner at Olive Garden Saturday at 6"* | Parses time/place/people, checks for conflicts, asks for confirmation, writes to the family calendar. |
| **Query** | *"What's happening this Friday?"* | Lists events on the requested day(s). |
| **Reschedule** | *"Move Layla's dentist to next Thursday at 3"* | Finds the matching event, asks to confirm the move, updates it. |
| **Delete** | *"Cancel the dentist appointment"* | Finds the event, asks for confirmation, deletes it. |
| **Weekly briefing** | *(automatic, Sunday 6 PM PT)* | Posts a recap of the upcoming week in the schedule channel. |

Mutating actions (create / reschedule / delete) always go through a Yup/Nope
button confirmation — the bot never silently changes the calendar.

## Architecture

The bot is a single async Python process with a layered architecture:

```
Discord channel
      |
      v
SchedulerCog  ----- discord.py message listener + weekly task
   |      \
   |       \---> ConfirmView   (Yup / Nope buttons)
   |
   +--> NLPService           (Anthropic Claude -> ParsedIntent JSON)
   |
   +--> CalendarService      (Google Calendar API, run in a thread pool)
              |
              v
       Google Calendar
```

### Layers

- `schedule_minion/main.py` — entry point. Loads `.env`, builds the bot,
  wires services into the cog, installs SIGTERM/SIGINT handlers, runs the
  event loop.
- `schedule_minion/config.py` — `Settings` dataclass loaded from
  environment variables. Supports either a credentials file path
  (`GOOGLE_CREDENTIALS_PATH`) or a JSON blob (`GOOGLE_CREDENTIALS_JSON`)
  for platforms like Railway that don't mount files.
- `schedule_minion/constants.py` — the family roster: name → email →
  calendar ID, plus aliases (`"daddy"` → `"dad"`, `"free"` → `"mom"`, …).
  This is the only place identities live.
- `schedule_minion/models/events.py` — pure data classes:
  `IntentType` (enum), `FamilyMember`, `ParsedIntent`, `CalendarEvent`.
- `schedule_minion/services/nlp_service.py` — wraps the Anthropic
  client. Sends the user's message plus current date/time to Claude with
  a system prompt describing the family and the JSON schema, then parses
  the response into a `ParsedIntent`.
- `schedule_minion/services/calendar_service.py` — wraps the Google
  Calendar API. All calls are sync, so they run in `loop.run_in_executor`
  to keep the event loop unblocked.
- `schedule_minion/cogs/scheduler.py` — the only piece that knows about
  Discord. Listens for mentions in the configured channel, routes parsed
  intents to handlers, attaches `ConfirmView`s, and runs the weekly
  briefing on a `tasks.loop`.
- `schedule_minion/views/confirmations.py` — generic `ConfirmView` with
  async `on_confirm` / `on_cancel` callbacks and a 120-second timeout.

### Code Choices

- **Async throughout.** discord.py and the Anthropic SDK are async
  natively; the Google Calendar client isn't, so its calls are
  off-loaded to the default executor.
- **Service-account auth (no OAuth dance).** This keeps setup tractable
  for a small family deployment. The trade-off: service accounts can't
  invite Gmail addresses as attendees without domain-wide delegation, so
  attendee names are persisted in the event description on a dedicated
  `Attendees: ...` line and parsed back out on read.
- **Frozen `Settings` dataclass.** Configuration is loaded once at
  startup and treated as immutable.
- **Single channel, single calendar.** The bot ignores any message
  outside `DISCORD_CHANNEL_ID` and writes to a single
  `FAMILY_CALENDAR_ID`. Everything else falls out of that constraint.
- **JSON-only LLM contract.** The system prompt instructs Claude to
  respond with JSON and nothing else; the parser strips a fenced code
  block if Claude adds one anyway.
- **Confirmation by default.** Every mutating intent goes through a
  `ConfirmView`. There is no "yolo" path.
- **Family identities centralized.** Every alias / email / calendar
  lives in `constants.py`. Adding or renaming a family member is a
  one-file change.

## Bot API (the things you can say)

The "API" is natural language, but it has shape. Claude is instructed to
return this JSON envelope:

```json
{
  "intent": "create" | "query" | "reschedule" | "delete" | "unknown",
  "title": "Event Name" | null,
  "start_time": "ISO 8601 datetime" | null,
  "end_time":   "ISO 8601 datetime" | null,
  "location":   "string" | null,
  "people":     ["dad", "mom", "layla", "niall"] | [],
  "search_query": "string to match event title" | null,
  "notes":        "any extra context" | null
}
```

Conventions:

- **People.** Empty `people` means the whole family. Names and aliases
  (see `constants.py`) are case-insensitive.
- **Times.** Claude is given the current date/time and timezone in the
  user prompt so it can resolve "next Friday", "tomorrow at 6", etc. If
  no end time is given, handlers default to a 1-hour duration.
- **Titles.** For `create` intents, Claude generates a short, slightly
  playful title (2–4 words).
- **Unknown.** If Claude can't classify the intent, the bot replies
  with an example and stops.

### Internal service interfaces

`NLPService.parse_message(message: str) -> ParsedIntent`
  Calls Claude (`claude-sonnet-4-5-20250929`), parses the JSON,
  resolves names to `FamilyMember`s, returns a `ParsedIntent`.

`CalendarService` (all methods are async):
- `create_event(calendar_id, title, start_time, end_time, attendees=None, location=None) -> CalendarEvent`
- `get_events(calendar_ids, time_min, time_max) -> list[CalendarEvent]`
- `update_event(calendar_id, event_id, title=None, start_time=None, end_time=None, location=None) -> CalendarEvent`
- `delete_event(calendar_id, event_id) -> bool`
- `find_conflicts(calendar_ids, start_time, end_time) -> list[CalendarEvent]`

`ConfirmView(on_confirm, on_cancel=None, timeout=120.0)`
  Posts Yup/Nope buttons; on click, runs the callback, edits the
  message with the result, disables the buttons.

## Configuration

Copy `.env.example` to `.env` and fill in:

| Variable | Required | Description |
|---|---|---|
| `DISCORD_TOKEN` | yes | Discord bot token. |
| `DISCORD_CHANNEL_ID` | yes | The single channel the bot listens in. |
| `ANTHROPIC_API_KEY` | yes | API key for Claude NLP parsing. |
| `FAMILY_CALENDAR_ID` | yes | Google Calendar ID for the shared family calendar. |
| `GOOGLE_CREDENTIALS_PATH` | one of | Path to a service-account JSON file. |
| `GOOGLE_CREDENTIALS_JSON` | one of | Service-account JSON inlined as a string (for Railway, Heroku, etc.). |

The bot's timezone defaults to `America/Los_Angeles` and is set on the
`Settings` dataclass.

## Installation

```bash
git clone <repository-url>
cd schedule-minion

pip install -r requirements-dev.txt
pre-commit install

cp .env.example .env
# fill in tokens, IDs, paths
```

## Running

```bash
python -m schedule_minion.main
```

The repo also ships a `Procfile` (`worker: python -m schedule_minion.main`)
so it deploys cleanly to Railway / Heroku-style platforms.

## Development

This project is built under the
[Start Green / Stay Green](https://github.com/Geoffe-Ga/start_green_stay_green)
maximum-quality workflow. The non-negotiable rules are in [CLAUDE.md](CLAUDE.md);
the short version:

- Always invoke tooling via `./scripts/*` rather than the underlying
  binaries directly — that keeps local and CI behavior identical.
- Operate from the project root; CI does, and `cd`-ing into subdirs
  breaks reproducibility.
- Run `./scripts/check-all.sh` before every commit. Don't push red.

### Scripts

```bash
./scripts/test.sh          # pytest with coverage
./scripts/lint.sh          # ruff + pylint + mypy
./scripts/format.sh --fix  # auto-format with ruff/black
./scripts/typecheck.sh     # mypy (strict)
./scripts/security.sh      # bandit + pip-audit
./scripts/complexity.sh    # radon + xenon
./scripts/coverage.sh      # coverage report (--html for browser view)
./scripts/check-all.sh     # everything above
./scripts/fix-all.sh       # auto-fix what can be auto-fixed
```

### Quality gates

- Test coverage ≥ 90% (branch coverage ≥ 85% in CI).
- Cyclomatic complexity ≤ 10 per function.
- mypy in strict mode; full type hints.
- Ruff, Pylint, Bandit, pip-audit all clean.
- 32 pre-commit hooks gate every commit.

CI runs the same matrix on Python 3.11 / 3.12 / 3.13.

## Project Layout

```
schedule-minion/
├── schedule_minion/
│   ├── main.py                  # entry point
│   ├── config.py                # Settings dataclass
│   ├── constants.py             # family roster + aliases
│   ├── cogs/
│   │   └── scheduler.py         # Discord listener + weekly task
│   ├── models/
│   │   └── events.py            # IntentType, FamilyMember, ParsedIntent, CalendarEvent
│   ├── services/
│   │   ├── nlp_service.py       # Claude NLP parsing
│   │   └── calendar_service.py  # Google Calendar wrapper
│   └── views/
│       └── confirmations.py     # Yup/Nope button view
├── tests/                       # pytest (unit + integration)
├── scripts/                     # check-all.sh, test.sh, lint.sh, ...
├── plans/                       # build plan + ADRs
├── .github/workflows/           # CI + code review
├── pyproject.toml               # tool config (ruff, mypy, coverage, ...)
├── requirements.txt
├── requirements-dev.txt
├── Procfile                     # `worker: python -m schedule_minion.main`
└── CLAUDE.md                    # project conventions for AI agents
```

## License

MIT.

## Attribution

Bootstrapped with
[Start Green Stay Green](https://github.com/Geoffe-Ga/start_green_stay_green) —
maximum-quality Python projects from day one.
