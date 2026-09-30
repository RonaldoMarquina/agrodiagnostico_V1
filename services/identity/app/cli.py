"""CLI commands for Identity service administrative provisioning."""
import argparse
import sys
from app.domain.models import AuditLog, User
from app.infrastructure.security import hash_password, validate_password_policy
from app.persistence import get_sessionmaker


def create_initial_admin(email: str, password: str, display_name: str) -> int:
    """Safely provision the initial ADMIN account."""
    email_clean = email.strip().lower()
    if "@" not in email_clean:
        print("Error: Invalid email format", file=sys.stderr)
        return 1

    if not validate_password_policy(password):
        print("Error: Password does not meet policy requirements (12-128 characters)", file=sys.stderr)
        return 1

    session_maker = get_sessionmaker()
    with session_maker() as db:
        existing = db.query(User).filter(User.email == email_clean).first()
        if existing:
            if existing.role == "ADMIN":
                print("Notice: Administrator account already exists.", file=sys.stderr)
                return 0
            print("Error: An account already exists with that email but is not an administrator.", file=sys.stderr)
            return 1

        admin = User(
            email=email_clean,
            password_hash=hash_password(password),
            display_name=display_name.strip(),
            role="ADMIN",
            status="ACTIVE",
        )
        db.add(admin)
        db.flush()

        # Audit initial admin creation
        db.add(AuditLog(
            user_id=admin.id,
            event_type="INITIAL_ADMIN_CREATED",
            details={"email": admin.email},
        ))
        db.commit()
        print(f"Successfully provisioned initial administrator: {admin.email}")
        return 0


def main():
    parser = argparse.ArgumentParser(description="Identity administrative CLI")
    subparsers = parser.add_subparsers(dest="command")

    admin_parser = subparsers.add_parser("create-admin", help="Provision initial administrator")
    admin_parser.add_argument("--email", required=True, help="Administrator email")
    admin_parser.add_argument("--password", required=True, help="Administrator password (12-128 chars)")
    admin_parser.add_argument("--name", default="Administrador", help="Display name")

    args = parser.parse_args()
    if args.command == "create-admin":
        return create_initial_admin(args.email, args.password, args.name)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
