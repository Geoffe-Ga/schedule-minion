## Problem

On Railway, credentials are injected as environment variables, not files.
The current implementation works around this by writing `GOOGLE_CREDENTIALS_JSON`
to a temporary file (`_write_credentials_file`), then loading that file via
`from_service_account_file()`. This is fragile and unnecessary — the Google
Auth library natively supports `from_service_account_info()` which accepts a
dict directly.

## Proposed Solution

- Add `google_credentials_info: dict | None` to `Settings` alongside the
  existing `google_credentials_path`
- Have `CalendarService` use `from_service_account_info()` when a dict is
  provided, `from_service_account_file()` when a path is provided
- Remove the `_write_credentials_file` temp-file helper from `config.py`

## Acceptance Criteria

- [ ] `GOOGLE_CREDENTIALS_JSON` env var loads credentials via `from_service_account_info()` (no temp file)
- [ ] `GOOGLE_CREDENTIALS_PATH` env var still works via `from_service_account_file()`
- [ ] `_write_credentials_file` removed
- [ ] `tempfile` import removed from config.py
- [ ] All existing tests updated, all checks green
