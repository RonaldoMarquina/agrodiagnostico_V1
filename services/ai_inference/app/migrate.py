"""Sanitized entry point for one-shot Alembic and schema readiness checks."""
import argparse
from alembic import command
from app.persistence import config, schema_ready


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["upgrade", "current", "downgrade", "ready"])
    parser.add_argument("revision", nargs="?")
    args = parser.parse_args()
    try:
        if args.action == "ready":
            ok = schema_ready()
            print("schema_ready" if ok else "schema_not_ready")
            return 0 if ok else 1
        if args.action == "upgrade":
            command.upgrade(config(), args.revision or "head")
            if not schema_ready():
                raise RuntimeError("Expected revision absent")
        elif args.action == "downgrade":
            if not args.revision:
                parser.error("downgrade requires explicit revision")
            command.downgrade(config(), args.revision)
        else:
            command.current(config())
        return 0
    except Exception:
        print("migration_failed: verify configuration, database and revision")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
