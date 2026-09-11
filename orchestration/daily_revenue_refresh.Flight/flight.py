# orchestration/daily_revenue_refresh.Flight/flight.py — dbt workload on MotherDuck.
#
# Runs in the MotherDuck Flight runtime: CPython 3.12, dependencies installed by
# uv from the sibling requirements.txt, /tmp writable, git on PATH, unrestricted
# network egress.
#
# Every knob is read from Flight config so the program is adapted by setting
# config values, never by editing code. Each key MUST be declared in config.json:
# MD_RUN_FLIGHT rejects a per-run override for an undeclared key.
#
# RUN CONTRACT — this file is deployed and executed only by
# `running-orchestration-in-sandbox`, which passes it as the Flight's source_code.
import json
import os
import re
import subprocess
import sys
import tempfile


def env(name: str) -> str:
    return os.environ[name]


IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def identifier(name: str) -> str:
    # The database name reaches CREATE DATABASE, which cannot be parameterised,
    # so it is checked before any SQL runs.
    value = env(name)
    if not IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"{name} must be a plain SQL identifier, got {value!r}")
    return value


def checkout(repo: str, revision: str, destination: str) -> None:
    # Fetch the approved revision explicitly instead of cloning a branch tip, so
    # the run is reproducible and matches what the intent approved.
    subprocess.run(["git", "init", "--quiet", destination], check=True)
    subprocess.run(["git", "-C", destination, "remote", "add", "origin", repo], check=True)
    subprocess.run(["git", "-C", destination, "fetch", "--quiet", "--depth", "1",
                    "origin", revision], check=True)
    subprocess.run(["git", "-C", destination, "checkout", "--quiet", "FETCH_HEAD"], check=True)


def write_profile(directory: str, database: str, schema: str) -> None:
    # The database is named explicitly. A Flight that names none connects to
    # `my_db` and the write still reports success.
    with open(os.path.join(directory, "profiles.yml"), "w") as handle:
        handle.write(
            "flight:\n"
            "  target: prod\n"
            "  outputs:\n"
            "    prod:\n"
            "      type: duckdb\n"
            f'      path: "md:{database}"\n'
            f"      schema: {schema}\n")


def main() -> None:
    # dbt writes working files under HOME; a Flight has a writable /tmp.
    os.environ["HOME"] = "/tmp"
    database = identifier("DESTINATION_DATABASE")
    schema = env("DBT_SCHEMA")
    selector = env("DBT_SELECT")
    revision = env("GIT_REVISION")

    # dbt-duckdb ATTACHes md:<database> and does not create it, so a run against
    # a database that does not exist yet dies on "no database/share named ...".
    import duckdb

    con = duckdb.connect("md:")
    con.execute(f"CREATE DATABASE IF NOT EXISTS {database}")
    con.close()

    workdir = tempfile.mkdtemp()
    project = os.path.join(workdir, "project")
    profiles = os.path.join(workdir, "profiles")
    os.makedirs(profiles)

    checkout(env("GIT_REPO"), revision, project)
    print("checked out revision:", revision)
    write_profile(profiles, database, schema)

    # A Domain repository keeps its dbt project in a subdirectory, so the
    # checkout root is rarely the project root: set DBT_PROJECT_SUBDIR to
    # whichever directory holds dbt_project.yml, or "." when it is the root.
    project_dir = os.path.normpath(os.path.join(project, env("DBT_PROJECT_SUBDIR")))
    if not os.path.exists(os.path.join(project_dir, "dbt_project.yml")):
        raise FileNotFoundError(
            f"no dbt_project.yml under DBT_PROJECT_SUBDIR={env('DBT_PROJECT_SUBDIR')!r}")

    from dbt.cli.main import dbtRunner

    # One deliberate `build --select` per Flight: dbt owns the model graph, and
    # individual models are never separate orchestration activities.
    result = dbtRunner().invoke(
        ["build", "--select", selector,
         "--project-dir", project_dir, "--profiles-dir", profiles, "--profile", "flight"])

    run_results = os.path.join(project_dir, "target", "run_results.json")
    if os.path.exists(run_results):
        with open(run_results) as handle:
            summary = json.load(handle)
        print("dbt nodes:", len(summary.get("results", [])),
              "elapsed:", summary.get("elapsed_time"))

    # A dbt failure does NOT fail the Flight on its own: dbtRunner reports
    # success=False without raising, so without this the run reports
    # RUN_STATUS_SUCCEEDED with exit_code 0 over a broken graph.
    if not result.success:
        failed = [node.node.unique_id for node in (result.result or [])
                  if str(node.status) not in ("success", "pass")]
        print("dbt FAILED:", ", ".join(failed) or "see logs", file=sys.stderr)
        sys.exit(1)
    print("dbt build succeeded for selector:", selector)


if __name__ == "__main__":
    main()
