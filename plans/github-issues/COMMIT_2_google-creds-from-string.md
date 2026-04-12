feat(config): load Google credentials from string via from_service_account_info

Replace temp-file workaround with direct dict-based credential loading.
CalendarService now accepts credentials_info (dict) and uses
google.oauth2.service_account.Credentials.from_service_account_info()
when available, falling back to from_service_account_file() for
file-path-based credentials. Removes _write_credentials_file helper
and tempfile dependency from config.py.

Refs #2
