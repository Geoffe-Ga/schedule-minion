# Schedule Minion

> A calendar service that protects invisible labor by giving a family a shared
> calendar they can add to in plain English — via RubotPaul, the household
> assistant.

## Mission

Most household coordination — the doctor's appointments, the carpool swap, the
"don't forget Layla has dance Thursday" — is **invisible labor**. It rarely
shows up on a to-do list, it almost never gets credit, and it almost always
falls on one person.

Schedule Minion is a small attempt to make that work visible and shareable.
Anyone in the family — kid, parent, the parent who handles "everything else" —
can drop a sentence into chat and the calendar updates for everybody. No app
to learn. No form to fill. No "I thought *you* were going to put it on the
calendar."

The service does the boring part. The mental load gets distributed instead of
hoarded.

## What It Does

Schedule Minion is an HTTP API consumed by RubotPaul (the household assistant,
which owns the Discord conversation). RubotPaul parses what the family says,
calls this service, and posts the results back to chat. The service exposes:

| Capability | Endpoint | Behavior |
|---|---|---|
| **List events** | `GET /api/v1/events?from=&to=` | Events in a window (default: next 7 days, max 60). |
| **Parse intent** | `POST /api/v1/events/parse` | Runs the Claude NLP parser over free-form text, returns `{intent, confidence, fields}`. |
| **Create** | `POST /api/v1/events/create` | Conflict-checks, then *stages* the creation for confirmation. |
| **Reschedule** | `POST /api/v1/events/reschedule` | Verifies the event exists, then stages the move. |
| **Delete** | `DELETE /api/v1/events/{event_id}` | Verifies the event exists, then stages the deletion. |
| **Confirm** | `POST /api/v1/events/confirm` | Applies a staged action exactly once. |
| **Liveness** | `GET /healthz` | Unauthenticated `{"ok": true}` probe. |

Mutating actions (create / reschedule / delete) always go through the
draft → confirm → execute flow: the endpoint stages a pending action (5-minute
TTL) and returns a preview; RubotPaul posts the draft in chat and only calls
`/events/confirm` after the user explicitly says "confirm". The service never
silently changes the calendar.

All `/api/v1` routes require the RubotPaul HMAC bearer token
(`Authorization: Bearer <caller_id>.<timestamp>.<hmac_hex>` signed with
`RUBOTPAUL_SHARED_SECRET`).

## Architecture

The service is a single async Python process with a layered architecture:

```
RubotPaul (owns Discord)
      |  HMAC bearer over localhost:8003
      v
aiohttp API (api.py)  ----- staged pending-confirmation for writes
   |
   +--> NLPService           (Anthropic Claude -> ParsedIntent JSON)
   |
   +--> CalendarService      (Google Calendar API, run in a thread pool)
              |
              v
       Google Calendar
```

### Layers

- `schedule_minion/api.py` — the aiohttp application and the service
  entrypoint. `build_app()` wires dependency-injected services into the
  authenticated `/api/v1` subapp; `serve()` / `main()` run the standalone
  process with graceful SIGTERM/SIGINT shutdown.
- `schedule_minion/auth_middleware.py` — vendored RubotPaul HMAC bearer
  middleware shared by all household services.
- `schedule_minion/config.py` — frozen `ApiSettings` dataclass loaded from
  environment variables, failing fast at boot with every missing variable
  named. Supports either a credentials file path (`GOOGLE_CREDENTIALS_PATH`)
  or a JSON blob (`GOOGLE_CREDENTIALS_JSON`) for platforms that don't mount
  files.
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

The standalone Discord bot (message listener cog, Yup/Nope button views, and
the Sunday 6 PM weekly-summary loop) was retired when RubotPaul took over the
Discord side; the weekly briefing now lives in RubotPaul's scheduler, which
calls `GET /api/v1/events` and formats the recap itself.

### Code Choices

- **Async throughout.** aiohttp and the Anthropic SDK are async
  natively; the Google Calendar client isn't, so its calls are
  off-loaded to the default executor.
- **Service-account auth (no OAuth dance).** This keeps setup tractable
  for a small family deployment. The trade-off: service accounts can't
  invite Gmail addresses as attendees without domain-wide delegation, so
  attendee names are persisted in the event description on a dedicated
  `Attendees: ...` line and parsed back out on read.
- **Frozen `ApiSettings` dataclass.** Configuration is loaded once at
  startup, validated eagerly, and treated as immutable.
- **Single calendar.** The service writes to a single
  `FAMILY_CALENDAR_ID`. Everything else falls out of that constraint.
- **JSON-only LLM contract.** The system prompt instructs Claude to
  respond with JSON and nothing else; the parser strips a fenced code
  block if Claude adds one anyway.
- **Confirmation by default.** Every mutating endpoint stages a pending
  action and returns a preview; nothing touches Google Calendar until
  the confirm call. There is no "yolo" path.
- **Conflict check before staging.** `/events/create` returns its 409
  (with the conflicting events) *before* staging, so pending actions
  can't be used to probe the calendar.
- **Family identities centralized.** Every alias / email / calendar
  lives in `constants.py`. Adding or renaming a family member is a
  one-file change.

## NLP contract (what `/events/parse` returns)

The parser's "API" is natural language, but it has shape. Claude is
instructed to return this JSON envelope, surfaced by the endpoint as
`{intent, confidence, fields}`:

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
  user prompt so it can resolve "next Friday", "tomorrow at 6", etc.
- **Titles.** For `create` intents, Claude generates a short, slightly
  playful title (2–4 words).
- **Unknown.** If Claude can't classify the intent, RubotPaul replies
  with an example and stops.

### Internal service interfaces

`NLPService.parse_message(message: str) -> ParsedIntent`
  Calls Claude (`claude-sonnet-4-5-20250929`), parses the JSON,
  resolves names to `FamilyMember`s, returns a `ParsedIntent`.

`CalendarService` (all methods are async):
- `create_event(calendar_id, title, start_time, end_time, attendees=None, location=None) -> CalendarEvent`
- `get_events(calendar_ids, time_min, time_max) -> list[CalendarEvent]`
- `get_event(calendar_ids, event_id) -> CalendarEvent`
- `update_event(calendar_id, event_id, title=None, start_time=None, end_time=None, location=None) -> CalendarEvent`
- `delete_event(calendar_id, event_id) -> bool`
- `find_conflicts(calendar_ids, start_time, end_time) -> list[CalendarEvent]`

## Configuration

Copy `.env.example` to `.env` and fill in:

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | yes | API key for Claude NLP parsing. |
| `FAMILY_CALENDAR_ID` | yes | Google Calendar ID for the shared family calendar. |
| `RUBOTPAUL_SHARED_SECRET` | yes | HMAC secret shared with the RubotPaul caller. |
| `GOOGLE_CREDENTIALS_PATH` | one of | Path to a service-account JSON file. |
| `GOOGLE_CREDENTIALS_JSON` | one of | Service-account JSON inlined as a string. |
| `SCHEDULE_MINION_API_PORT` | no | API port (default `8003`). |

The service's timezone defaults to `America/Los_Angeles` and is set on the
`ApiSettings` dataclass. The API binds `127.0.0.1` only — RubotPaul reaches
it over localhost on the shared VPS.

## Installation

```bash
git clone <repository-url>
cd schedule-minion

pip install -r requirements-dev.txt
pre-commit install

cp .env.example .env
# fill in keys, IDs, paths
```

## Running

```bash
python -m schedule_minion.api
```

Boot fails fast with a clear message naming every missing environment
variable. SIGINT/SIGTERM shut the server down gracefully, so it runs cleanly
as a `systemd --user` unit on the VPS, colocated with RubotPaul:

```ini
# ~/.config/systemd/user/schedule-minion.service
[Unit]
Description=Schedule Minion API (RubotPaul calendar service)
After=network.target

[Service]
WorkingDirectory=%h/schedule-minion
EnvironmentFile=%h/schedule-minion/.env
ExecStart=%h/schedule-minion/venv/bin/python -m schedule_minion.api
Restart=on-failure

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now schedule-minion
```

Calling the API (RubotPaul integration):

```bash
TOKEN="<caller_id>.<unix_ts>.$(printf '%s' "<caller_id>.<unix_ts>" \
  | openssl dgst -sha256 -hmac "$RUBOTPAUL_SHARED_SECRET" -hex | cut -d' ' -f2)"
curl -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8003/api/v1/events"
```

The repo also ships a `Procfile` (`web: python -m schedule_minion.api`) for
Heroku-style platforms.

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
│   ├── api.py                   # aiohttp app + standalone entrypoint
│   ├── auth_middleware.py       # vendored RubotPaul HMAC bearer auth
│   ├── config.py                # ApiSettings dataclass
│   ├── constants.py             # family roster + aliases
│   ├── models/
│   │   └── events.py            # IntentType, FamilyMember, ParsedIntent, CalendarEvent
│   └── services/
│       ├── nlp_service.py       # Claude NLP parsing
│       └── calendar_service.py  # Google Calendar wrapper
├── tests/                       # pytest (unit + integration)
├── scripts/                     # check-all.sh, test.sh, lint.sh, ...
├── plans/                       # build plan + ADRs
├── .github/workflows/           # CI + code review
├── pyproject.toml               # tool config (ruff, mypy, coverage, ...)
├── requirements.txt
├── requirements-dev.txt
├── Procfile                     # `web: python -m schedule_minion.api`
└── CLAUDE.md                    # project conventions for AI agents
```

## License

MIT.

## Attribution

Bootstrapped with
[Start Green Stay Green](https://github.com/Geoffe-Ga/start_green_stay_green) —
maximum-quality Python projects from day one.
