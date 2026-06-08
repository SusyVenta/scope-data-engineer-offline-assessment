"""
conftest.py
-----------
Shared pytest fixtures for the corporate ratings pipeline test suite.
"""

from __future__ import annotations

import os
import smtplib
import socket
from email.message import EmailMessage
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Email notification on test failure
# ---------------------------------------------------------------------------

def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Send an email alert when any test fails."""
    if exitstatus == 0:
        return

    alert_email = os.getenv("ALERT_EMAIL", "")
    smtp_host = os.getenv("AIRFLOW__SMTP__SMTP_HOST", "")
    smtp_port = int(os.getenv("AIRFLOW__SMTP__SMTP_PORT", "587"))
    smtp_user = os.getenv("AIRFLOW__SMTP__SMTP_USER", "")
    smtp_password = os.getenv("AIRFLOW__SMTP__SMTP_PASSWORD", "")
    smtp_from = os.getenv("AIRFLOW__SMTP__SMTP_MAIL_FROM", smtp_user)
    use_tls = os.getenv("AIRFLOW__SMTP__SMTP_STARTTLS", "true").lower() == "true"

    if not all([alert_email, smtp_host, smtp_user, smtp_password]):
        return

    failed = getattr(session, "testsfailed", 0)
    host = socket.gethostname()

    msg = EmailMessage()
    msg["Subject"] = f"[TEST FAILURE] {failed} test(s) failed on {host}"
    msg["From"] = smtp_from
    msg["To"] = alert_email
    msg.set_content(
        f"{failed} test(s) failed during the pytest session on host '{host}'.\n\n"
        f"Exit status: {exitstatus}\n"
        f"Total collected: {session.testscollected}\n\n"
        f"Check the container logs for the full traceback:\n"
        f"  docker compose logs tests\n"
        f"  docker compose logs integration-tests\n"
    )

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            if use_tls:
                server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Path fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def project_root() -> Path:
    return Path(__file__).parent.parent


@pytest.fixture(scope="session")
def input_files_dir(project_root: Path) -> Path:
    return project_root / "data" / "input_files"


@pytest.fixture(scope="session")
def extracted_sheets_dir(project_root: Path, tmp_path_factory) -> Path:
    """Temporary directory for extracted sheet CSVs during tests."""
    return tmp_path_factory.mktemp("extracted_sheets")


@pytest.fixture(scope="session")
def all_xlsm_files(input_files_dir: Path) -> list[Path]:
    return sorted(input_files_dir.glob("*.xlsm"))
