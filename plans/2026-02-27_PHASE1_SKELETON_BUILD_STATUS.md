# Phase 1: Skeleton Build — Status & Next Steps

> Tracer code implementation of Schedule Minion Discord bot.

---

## What Was Done

### Pre-work: Dependency Cleanup

Before building, we removed heavyweight/problematic dev dependencies:

- **Removed mutmut** (mutation testing) from requirements-dev.txt, pyproject.toml, CI, scripts, CLAUDE.md, README, and skills
- **Removed interrogate** (docstring coverage enforcer) from pre-commit hooks and CI
- **Fixed "Safety" references** in scripts to correctly say "pip-audit"
- **Deleted** `scripts/mutation.sh`, `scripts/analyze_mutations.py`, `.claude/skills/mutation-testing/`
- **Simplified Stay Green** from 4 gates to 3 gates (local checks → CI → code review)

### Phase 1 Build Progress (Tracer Code Skeleton)

Following the plan in `plans/schedule-minion-plan.md`, using TDD (Red-Green-Refactor):

#### Completed

1. **Runtime dependencies installed** — Added discord.py, anthropic, google-api-python-client, google-auth, python-dotenv, httpx, python-dateutil to `requirements.txt` and installed into `.venv`

2. **Package structure created** — Directories for the layered architecture:
   ```
   schedule_minion/
   ├── models/       ✅ Created
   ├── services/     ✅ Created
   ├── cogs/         ✅ Created
   └── views/        ✅ Created
   ```

3. **Data models (TDD complete)** — `schedule_minion/models/events.py`
   - `IntentType` enum (CREATE, QUERY, RESCHEDULE, DELETE, UNKNOWN)
   - `FamilyMember` dataclass (name, email, calendar_id)
   - `ParsedIntent` dataclass (intent, title, times, location, people, search_query, etc.)
   - `CalendarEvent` dataclass (event_id, calendar_id, title, times, location, attendees, duration_str property)
   - **14 passing tests** in `tests/unit/test_models.py`, **96.23% coverage**

4. **Config module written** — `schedule_minion/config.py`
   - `Settings` frozen dataclass loaded from environment variables
   - `from_env()` classmethod
   - **Tests written** in `tests/unit/test_config.py` (4 tests)

5. **Constants module written** — `schedule_minion/constants.py`
   - `FAMILY_MEMBERS` dict (Dad, Mom, Layla, Niall with emails/calendar IDs)
   - `NAME_ALIASES` dict (geoff→dad, free→mom, etc.)
   - `ALL_FAMILY` list
   - **Tests written** in `tests/unit/test_constants.py` (10 tests)

#### Not Yet Verified

- Config and constants tests were written and the modules were created, but `pytest` was not run to confirm GREEN on those two modules (interrupted before verification)

---

## Next Steps

### Remaining Phase 1 (Skeleton with Stubs)

4. **Verify config/constants tests pass** — Run pytest on the new test files
5. **Create stub NLP service** — `schedule_minion/services/nlp_service.py` with hardcoded ParsedIntent return (TDD)
6. **Create stub Calendar service** — `schedule_minion/services/calendar_service.py` with fake CRUD responses (TDD)
7. **Create confirmation views** — `schedule_minion/views/confirmations.py` (ConfirmView with Yes/No buttons)
8. **Create scheduler cog** — `schedule_minion/cogs/scheduler.py` (message listener, intent router, weekly summary task)
9. **Update entry point** — `schedule_minion/main.py` (bot setup, cog loading, async run)
10. **Create `.env.example`** — Template with all required env vars
11. **Gate 1 check** — `./scripts/test.sh --all` passes, all tests green

### Phase 2 (Replace Stubs with Real Implementations)

12. **Real NLP service** — Replace stub with Claude API integration (anthropic SDK, system prompt, JSON parsing)
13. **Real Calendar service** — Replace stub with Google Calendar API (service account auth, async wrapper around sync SDK)
14. **Precise weekly summary timing** — Sunday 6 PM Pacific with timezone-aware `tasks.loop`
15. **Error handling** — JSONDecodeError, APIError, and generic exception handling in the cog

### Phase 3 (Polish)

16. **README with setup instructions** — Google Cloud service account + Discord bot setup checklists
17. **Edge cases** — All-day events, emoji-only messages, deduplication across calendars
18. **Gate 2 check** — `pre-commit run --all-files` all green

---

## Architecture Note

The plan uses `bot/` as the package name, but the existing project tooling (pyproject.toml, coverage config, pre-commit) all reference `schedule_minion/`. All imports have been adapted accordingly: `from schedule_minion.models.events import ...` instead of `from bot.models.events import ...`.
