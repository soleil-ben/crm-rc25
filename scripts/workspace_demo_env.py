"""Build, refresh or destroy the local database for trying the workspace (Phase 13D).

    backend/.venv/Scripts/python scripts/workspace_demo_env.py --create
    backend/.venv/Scripts/python scripts/workspace_demo_env.py --reset       # rebuild
    backend/.venv/Scripts/python scripts/workspace_demo_env.py --refresh-fx  # new demo rate
    backend/.venv/Scripts/python scripts/workspace_demo_env.py --destroy

One database, ``data/workspace_demo/solaris_workspace.demo.db``, holding only synthetic data:
``app.seed`` (demo staff, fictional customers on ``example.com``), then ``app.seed_pricing
--with-master`` (the sanitized Kango tariff, a fixed demo exchange rate, and an open Air
Standard master with three members). Nothing calls the bank or the vendor, and ``data/`` is
git-ignored.

Safety, as in ``scripts/uat_env.py``: production is refused; the target must sit in
``data/workspace_demo/`` and end in ``.demo.db``; the development database, the UAT directory
and whatever ``DATABASE_URL`` currently points at are refused by resolved path. ``--destroy``
deletes only that one validated file and its SQLite sidecars. ``.env`` is never read or
written by this script.

After ``--create`` it prints the two commands that start a backend and a dev server on that
database, and the sign-in for the Operations demo account.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
DEMO_DIR = REPO_ROOT / "data" / "workspace_demo"
DEMO_DB = DEMO_DIR / "solaris_workspace.demo.db"
DEMO_DB_SUFFIX = ".demo.db"
DEV_DB = REPO_ROOT / "data" / "solaris_crm.db"
UAT_DIR = REPO_ROOT / "data" / "uat"

#: The seed's demo password; these accounts cannot authenticate in production
#: (``app.core.demo_identity``).
DEMO_LOGIN = ("ops@demo.example.com", "SolarisDemo!2026")
BACKEND_PORT = 8000
FRONTEND_URL = "http://localhost:5173/workspace"


class SafetyError(RuntimeError):
    """A path or an environment was refused before anything was created or deleted."""


def validated_target(path: Path) -> Path:
    environment = os.environ.get("ENVIRONMENT", "development").strip().lower()
    if environment.startswith("prod"):
        raise SafetyError(f"ENVIRONMENT={environment!r}. This script never runs in production.")
    resolved = path.resolve()
    if not resolved.name.endswith(DEMO_DB_SUFFIX):
        raise SafetyError(f"{resolved} does not end in {DEMO_DB_SUFFIX}.")
    try:
        resolved.relative_to(DEMO_DIR.resolve())
    except ValueError:
        raise SafetyError(f"{resolved} is outside {DEMO_DIR}.") from None
    if resolved == DEV_DB.resolve():
        raise SafetyError(f"{resolved} is the development database.")
    try:
        resolved.relative_to(UAT_DIR.resolve())
        raise SafetyError(f"{resolved} is inside the UAT directory.")
    except ValueError:
        pass
    configured = os.environ.get("DATABASE_URL", "")
    if configured.startswith("sqlite"):
        current = Path(configured.split("///", 1)[-1]).expanduser()
        try:
            if current.resolve() == resolved:
                raise SafetyError(f"{resolved} is what DATABASE_URL currently points at.")
        except OSError:
            pass
    return resolved


def database_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def run_backend(args: list[str], path: Path) -> None:
    env = {
        **os.environ,
        "DATABASE_URL": database_url(path),
        "ENVIRONMENT": "development",
        "ALLOW_DEMO_SEED": "true",
    }
    result = subprocess.run(  # noqa: S603
        [sys.executable, *args], cwd=BACKEND_ROOT, env=env, capture_output=True, text=True
    )
    sys.stdout.write(result.stdout)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        raise RuntimeError(f"{' '.join(args)} failed with exit {result.returncode}")


def destroy(path: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(path) + suffix)
        if candidate.exists():
            candidate.unlink()


def create(path: Path, *, reset: bool) -> None:
    if reset:
        destroy(path)
    if path.exists():
        raise SafetyError(f"{path} already exists; use --reset to rebuild it.")
    path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Migrating {path}")
    run_backend(["-m", "alembic", "upgrade", "head"], path)
    print("Seeding synthetic staff, customers and shipments")
    run_backend(["-m", "app.seed"], path)
    print("Adding the demo tariff, exchange rate and an open air master")
    run_backend(["-m", "app.seed_pricing", "--with-master"], path)
    how_to_start(path)


def how_to_start(path: Path) -> None:
    email, password = DEMO_LOGIN
    print(
        "\nStart the backend (PowerShell, from the repository root):\n"
        f'  $env:DATABASE_URL = "{database_url(path)}"; $env:ENVIRONMENT = "development"; '
        f"backend\\.venv\\Scripts\\python -m uvicorn app.main:app --port {BACKEND_PORT} "
        "--app-dir backend\n"
        "Start the screens (a second window):\n"
        "  npm run dev --prefix frontend\n"
        f"Open {FRONTEND_URL} and sign in as {email} / {password} (Operations).\n"
        "The demo exchange rate counts as live for a day; run --refresh-fx for a new one."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--create", action="store_true")
    group.add_argument("--reset", action="store_true")
    group.add_argument("--refresh-fx", action="store_true")
    group.add_argument("--destroy", action="store_true")
    args = parser.parse_args(argv)
    try:
        path = validated_target(DEMO_DB)
        if args.destroy:
            destroy(path)
            print(f"Removed {path}")
        elif args.refresh_fx:
            if not path.exists():
                raise SafetyError(f"{path} does not exist; run --create first.")
            run_backend(["-m", "app.seed_pricing", "--refresh-fx"], path)
        else:
            create(path, reset=args.reset)
    except SafetyError as error:
        print(f"Refused: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
