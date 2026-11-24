"""Validate minimal environment and start uvicorn for the assistant extension."""
import os
import sys

import uvicorn

ALLOWED_ENVS = {"local", "test", "staging", "production"}


def main() -> int:
    app_env = os.environ.get("APP_ENV", "").strip()
    if app_env not in ALLOWED_ENVS:
        print("configuration_invalid: APP_ENV", flush=True)
        return 1
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, access_log=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
