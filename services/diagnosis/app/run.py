"""Validate required local configuration without exposing values before serving."""
import os
from pathlib import Path
import sys
import uvicorn
from app.persistence import SERVICE


def main():
    required = ["APP_ENV", "DB_HOST", "DB_PASSWORD_FILE"]
    if SERVICE == "diagnosis":
        required += [
            "S3_ENDPOINT_URL",
            "S3_REGION",
            "S3_BUCKET",
            "S3_CREDENTIALS_FILE",
            "JWT_PUBLIC_KEY_PATH",
            "CURSOR_SIGNING_KEY_FILE",
        ]
    for key in required:
        value = os.environ.get(key)
        if not value:
            print("configuration_invalid: " + key, flush=True)
            return 1
        if key.endswith("_FILE") or key.endswith("_PATH"):
            try:
                if not Path(value).read_text().strip():
                    raise ValueError()
            except Exception:
                print("configuration_invalid: " + key, flush=True)
                return 1
    if os.environ["APP_ENV"] != "local":
        print("configuration_invalid: APP_ENV (only local scaffold)", flush=True)
        return 1
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, access_log=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
