"""The health boundary (Task 8.1, GC-7).

This is the file to read first if you want to know whether Upstream keeps
patient data out of the environmental system. Everything here is about what
*cannot* happen: no environmental credential in this process, no patient column
in this schema, no small count in this table, and nothing but six aggregate
fields leaving the service.

The separation is meant to hold even when someone writes careless code later, so
most of these assertions are about configuration and schema constraints rather
than about the behaviour of a function.
"""
import os

import psycopg
import pytest
from clinical_stats.ingest import SUPPRESSION_THRESHOLD, ingest_measure_report
from fastapi import HTTPException

AREA = "zone-boundary-test"


def measure_report(count: int | None, *, syndrome="acute_gastroenteritis", **over) -> dict:
    report = {
        "resourceType": "MeasureReport",
        "status": "complete",
        "type": "summary",
        "measure": "https://upstream-onehealth.example/Measure/gi-presentations-by-area-day",
        "subject": {"reference": f"Group/{AREA}"},
        "period": {"start": "2026-09-22", "end": "2026-09-22"},
        "group": [
            {
                "code": {
                    "coding": [
                        {
                            "system": "https://upstream-onehealth.example/CodeSystem/syndrome",
                            "code": syndrome,
                        }
                    ]
                },
                **({"measureScore": {"value": count}} if count is not None else {}),
            }
        ],
    }
    report.update(over)
    return report


# --- Where this process can and cannot reach --------------------------------


def test_clinical_service_has_no_environmental_credential():
    """GC-7: the separation is configuration, not convention."""
    import clinical_stats.db as d

    assert "clinical" in d.DSN
    assert d.DSN != os.environ.get("DATABASE_URL")


def test_the_environmental_database_url_is_not_even_read():
    """A process that never reads the variable cannot accidentally connect."""
    import inspect

    import clinical_stats.db as d

    source = inspect.getsource(d)
    assert "DATABASE_URL" not in source.replace("CLINICAL_DATABASE_URL", "")


def test_the_container_is_given_no_environmental_credential():
    """The check above passes trivially where DATABASE_URL is unset -- which is the
    clinical container. This one reads what the container is actually given.

    Only three variables reach it, none names the environmental database, and it
    loads no env_file (which would hand it every secret in `.env`).
    """
    import pathlib

    compose = pathlib.Path(__file__).resolve().parents[3] / "docker-compose.yml"
    if not compose.exists():
        pytest.skip("docker-compose.yml is not in this image; the host run checks it")
    yaml = pytest.importorskip("yaml")
    service = yaml.safe_load(compose.read_text(encoding="utf-8"))["services"]["clinical"]
    assert "env_file" not in service
    env = service.get("environment") or {}
    names = set(env) if isinstance(env, dict) else {e.split("=", 1)[0] for e in env}
    assert names <= {"CLINICAL_DATABASE_URL", "EPISODE_API_BASE_URL",
                     "CLINICAL_DAILY_INTERVAL_S"}
    values = " ".join(str(v) for v in (env.values() if isinstance(env, dict) else env))
    assert "DATABASE_URL}" not in values.replace("CLINICAL_DATABASE_URL}", "")
    assert "/upstream" not in values


@pytest.mark.integration
def test_clinical_role_cannot_even_open_a_session_on_the_environmental_database():
    """The strongest form of the boundary, and the one that was missing.

    Postgres grants CONNECT on every database to PUBLIC, so this role could open
    a session on the environmental database. Table privileges denied every read,
    so nothing leaked -- but one later `GRANT ... TO PUBLIC`, or one table
    created by a superuser with default grants, would have opened it silently.
    CONNECT is revoked now, and this is what keeps it revoked.
    """
    environmental = os.environ["CLINICAL_DATABASE_URL"].rsplit("/", 1)[0] + "/upstream"
    with pytest.raises(psycopg.OperationalError, match="(?i)permission denied"):
        psycopg.connect(environmental, autocommit=True, connect_timeout=10)


@pytest.mark.integration
def test_clinical_role_cannot_see_the_environmental_event_log(clinical_conn):
    """A different database, not a different schema: the table is not even here."""
    with pytest.raises(psycopg.errors.UndefinedTable):
        clinical_conn.execute("SELECT count(*) FROM events")


@pytest.mark.integration
def test_clinical_role_cannot_install_a_way_to_reach_across(clinical_conn):
    """dblink is absent, and this role cannot add it.

    Asserting only that `dblink(...)` fails would pass for the wrong reason --
    the function does not exist on any of these databases. The real defence is
    that the role cannot create the extension that would provide it.
    """
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        clinical_conn.execute("CREATE EXTENSION dblink")


# --- What this schema can hold ----------------------------------------------


@pytest.mark.integration
def test_no_patient_identifier_can_be_stored(clinical_conn):
    """There is nowhere to put one, so no future code can put one there."""
    with clinical_conn.cursor() as cur:
        cur.execute(
            "SELECT lower(column_name) FROM information_schema.columns "
            "WHERE table_schema='public'"
        )
        columns = {r[0] for r in cur.fetchall()}
    forbidden = {
        "patient_id",
        "patient",
        "nhs_number",
        "mrn",
        "name",
        "given_name",
        "family_name",
        "dob",
        "date_of_birth",
        "postcode",
        "address",
        "email",
        "phone",
    }
    assert not (columns & forbidden), f"patient-level columns present: {columns & forbidden}"


@pytest.mark.integration
def test_the_schema_itself_rejects_a_suppressed_count(clinical_conn):
    """Suppression is a CHECK constraint, not a branch someone can forget."""
    with pytest.raises(psycopg.errors.CheckViolation):
        clinical_conn.execute(
            "INSERT INTO syndromic_counts (day, area_code, syndrome, count, source) "
            "VALUES ('2026-09-22', %s, 'acute_gastroenteritis', 3, 'test')",
            (AREA,),
        )


# --- Ingestion ---------------------------------------------------------------


@pytest.mark.integration
def test_small_counts_are_suppressed_on_ingest(clinical_counts):
    result = ingest_measure_report(measure_report(count=3))
    assert result == {"accepted": 0, "suppressed": 1}


@pytest.mark.integration
def test_counts_at_the_threshold_are_accepted(clinical_counts):
    assert ingest_measure_report(measure_report(count=SUPPRESSION_THRESHOLD))["accepted"] == 1


@pytest.mark.integration
def test_an_absent_score_is_suppressed_not_stored_as_zero(clinical_counts):
    """A report with no score means the publisher suppressed it. Zero would be a claim."""
    assert ingest_measure_report(measure_report(count=None))["suppressed"] == 1


@pytest.mark.integration
def test_a_suppressed_count_leaves_no_row_behind(clinical_conn, clinical_counts):
    ingest_measure_report(measure_report(count=2))
    with clinical_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM syndromic_counts WHERE area_code=%s", (AREA,))
        assert cur.fetchone()[0] == 0


@pytest.mark.integration
def test_re_ingesting_a_day_corrects_it_rather_than_duplicating_it(clinical_conn, clinical_counts):
    ingest_measure_report(measure_report(count=7))
    ingest_measure_report(measure_report(count=9))
    with clinical_conn.cursor() as cur:
        cur.execute(
            "SELECT count FROM syndromic_counts WHERE area_code=%s AND syndrome=%s",
            (AREA, "acute_gastroenteritis"),
        )
        rows = cur.fetchall()
    assert rows == [(9,)]


def test_only_a_measure_report_is_accepted():
    with pytest.raises(HTTPException) as caught:
        ingest_measure_report({"resourceType": "Observation", "id": "x"})
    assert caught.value.status_code == 400


def test_an_individual_report_is_rejected():
    """GC-7: `type: individual` means there is a patient behind it."""
    with pytest.raises(HTTPException) as caught:
        ingest_measure_report(measure_report(count=9, type="individual"))
    assert caught.value.status_code == 400


def test_a_report_carrying_a_patient_subject_is_rejected():
    """Belt and braces: the profile forbids it, and so does this."""
    report = measure_report(count=9)
    report["subject"] = {"reference": "Patient/123"}
    with pytest.raises(HTTPException) as caught:
        ingest_measure_report(report)
    assert caught.value.status_code == 400


def test_a_report_with_an_evaluated_resource_is_rejected():
    """`evaluatedResource` is how a MeasureReport points at the records behind it."""
    report = measure_report(count=9)
    report["evaluatedResource"] = [{"reference": "List/patients-in-the-numerator"}]
    with pytest.raises(HTTPException) as caught:
        ingest_measure_report(report)
    assert caught.value.status_code == 400
