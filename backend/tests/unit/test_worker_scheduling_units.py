"""Regression: every background worker that exists must actually be
scheduled by the deployment configuration.

THE GAP THIS PINS DOWN
----------------------
`app/workers/reservation_expiry.py` (ADR-6) and `app/workers/receipt_purge.py`
(ADR-9) both existed with working `run_once()` logic and passing tests, but
nothing anywhere ever called them: no systemd unit, no timer, no call site
in `app/` or `bot/`. Deployed as-is, reservation TTLs would never fire (so
stock reserved by abandoned orders leaks permanently) and receipts would be
kept past their retention window — with a green test suite the whole time.

These are file-content assertions, not systemd runtime assertions. systemd
cannot be exercised in the verification environment (no root, no unit
installation), so this proves the units are *present and correct*, not that
they *ran*. See docs/tasks/Phase-09-Deploy.md for that distinction.
"""
from __future__ import annotations

import configparser
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SYSTEMD_DIR = REPO_ROOT / "deploy" / "systemd"
WORKERS_DIR = REPO_ROOT / "backend" / "app" / "workers"

# worker module -> (service unit, timer unit, expected OnCalendar)
SCHEDULED_WORKERS = {
    "reservation_expiry": (
        "comfort-reservation-expiry.service",
        "comfort-reservation-expiry.timer",
        "*:0/5",                 # every 5 minutes (§15)
    ),
    "receipt_purge": (
        "comfort-receipt-purge.service",
        "comfort-receipt-purge.timer",
        "*-*-* 03:30:00",        # daily (ADR-9 retention)
    ),
}


def _unit(name: str) -> configparser.ConfigParser:
    path = SYSTEMD_DIR / name
    assert path.exists(), f"missing systemd unit: {name}"
    parser = configparser.ConfigParser(strict=False)
    # systemd keys are case-sensitive; configparser lowercases by default.
    parser.optionxform = str
    parser.read(path, encoding="utf-8")
    return parser


def test_every_worker_module_is_scheduled():
    """The guard against the original bug: a worker module that no unit
    invokes is a worker that silently never runs."""
    modules = {
        p.stem
        for p in WORKERS_DIR.glob("*.py")
        if not p.stem.startswith("_") and p.stem != "__init__"
    }
    unscheduled = modules - set(SCHEDULED_WORKERS)
    assert not unscheduled, (
        f"worker module(s) {sorted(unscheduled)} have no systemd unit. Either add a "
        f"service+timer under deploy/systemd/ or add them to this test's "
        f"SCHEDULED_WORKERS map with a deliberate justification."
    )


@pytest.mark.parametrize("module,units", SCHEDULED_WORKERS.items())
def test_service_unit_invokes_the_worker_module(module, units):
    service_name, _, _ = units
    service = _unit(service_name)
    exec_start = service["Service"]["ExecStart"]
    assert f"-m app.workers.{module}" in exec_start, exec_start
    assert exec_start.startswith("/opt/comfort/backend/.venv/bin/python"), exec_start
    assert service["Service"]["Type"] == "oneshot"
    assert service["Service"]["User"] == "comfort"
    assert service["Service"]["Group"] == "comfort"
    assert service["Service"]["WorkingDirectory"] == "/opt/comfort/backend"
    assert service["Service"]["EnvironmentFile"] == "/etc/comfort/backend.env"
    # Failures must be visible in the journal.
    assert service["Service"]["StandardError"] == "journal"
    # Never root (§12.5).
    assert service["Service"]["NoNewPrivileges"] == "true"
    assert service["Service"]["ProtectSystem"] == "strict"
    assert service["Unit"]["After"].find("postgresql.service") != -1


@pytest.mark.parametrize("module,units", SCHEDULED_WORKERS.items())
def test_timer_targets_its_service_and_survives_downtime(module, units):
    service_name, timer_name, on_calendar = units
    timer = _unit(timer_name)
    assert timer["Timer"]["OnCalendar"] == on_calendar
    assert timer["Timer"]["Unit"] == service_name
    # Work missed while the box was down must still be picked up: expired
    # reservations keep holding stock until something releases them.
    assert timer["Timer"]["Persistent"] == "true"
    assert timer["Install"]["WantedBy"] == "timers.target"


def test_receipt_purge_runs_after_the_nightly_backup():
    """ADR-9 purges the file permanently. It must run after comfort-backup
    so the file is captured in that night's backup first."""
    purge = _unit("comfort-receipt-purge.timer")["Timer"]["OnCalendar"]
    backup = _unit("comfort-backup.timer")["Timer"]["OnCalendar"]
    assert purge > backup, f"purge at {purge} must be later than backup at {backup}"


def test_workers_are_not_also_started_inside_the_api_process():
    """No duplicate scheduling: the workers run as their own short-lived
    processes, never inside comfort-api's lifespan, where they would
    compete with request handling for the event loop and pool. (The bot is
    deliberately different — ADR-1 keeps it in-process.)"""
    main_py = (REPO_ROOT / "backend" / "app" / "main.py").read_text(encoding="utf-8")
    assert "reservation_expiry" not in main_py
    assert "receipt_purge" not in main_py
    assert "app.workers" not in main_py


# --- Unit installation -------------------------------------------------------
# Units that exist but are never installed/enabled are the same class of bug as
# workers that exist but are never scheduled: everything looks present, nothing
# ever runs. bootstrap.sh is the one-time host provisioning step, so that is
# where installation belongs (deploy.sh is per-release).

BOOTSTRAP = REPO_ROOT / "deploy" / "scripts" / "bootstrap.sh"


def test_bootstrap_installs_and_enables_the_units():
    script = BOOTSTRAP.read_text(encoding="utf-8")
    assert "/etc/systemd/system" in script, "bootstrap.sh never installs the unit files"
    assert "systemctl daemon-reload" in script
    assert "systemctl enable comfort-api.service" in script
    # Every timer is enabled by the glob loop, so a newly added timer is picked
    # up automatically rather than needing a manual edit here.
    assert "systemctl enable --now" in script
    assert '"$UNIT_SRC"/*.timer' in script


def test_every_unit_file_would_be_installed_by_the_glob():
    """The install step globs *.service and *.timer — assert every unit in
    deploy/systemd/ actually matches one of those patterns, so nothing is
    silently left behind."""
    for unit in SYSTEMD_DIR.iterdir():
        assert unit.suffix in {".service", ".timer"}, (
            f"{unit.name} is neither a .service nor a .timer, so bootstrap.sh's "
            f"install glob would skip it"
        )


def test_comfort_api_is_enabled_but_not_started_before_env_exists():
    """comfort-api must not be started by bootstrap.sh: /etc/comfort/backend.env
    is operator-owned and deliberately not created by the script, so starting
    the service there would only produce a crash loop."""
    script = BOOTSTRAP.read_text(encoding="utf-8")
    assert "systemctl enable --now comfort-api.service" not in script
    assert "systemctl start comfort-api.service" not in script
