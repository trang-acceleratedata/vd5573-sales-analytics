#!/usr/bin/env python3
"""
Daily revenue table refresh Flight.
Runs dbt build to refresh the daily_revenue mart table.
"""

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
    """Validate and return a SQL identifier from environment."""
    value = env(name)
    if not IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"{name} must be a plain SQL identifier, got {value!r}")
    return value


def checkout(repo: str, revision: str, destination: str) -> None:
    """Clone the approved revision from git."""
    subprocess.run(["git", "init", "--quiet", destination], check=True)
    subprocess.run(["git", "-C", destination, "remote", "add", "origin", repo], check=True)
    subprocess.run(["git", "-C", destination, "fetch", "--quiet", "--depth", "1",
                    "origin", revision], check=True)
    subprocess.run(["git", "-C", destination, "checkout", "--quiet", "FETCH_HEAD"], check=True)


def write_profile(directory: str, database: str, schema: str) -> None:
    """Write dbt profiles.yml with explicit database naming for MotherDuck."""
    with open(os.path.join(directory, "profiles.yml"), "w") as handle:
        handle.write(
            "flight:\n"
            "  target: prod\n"
            "  outputs:\n"
            "    prod:\n"
            "      type: motherduck\n"
            f'      database: "{database}"\n'
            f"      schema: {schema}\n"
            "      threads: 4\n")


def main() -> None:
    """Execute dbt build for daily_revenue model."""
    os.environ["HOME"] = "/tmp"
    database = identifier("DESTINATION_DATABASE")
    schema = env("DBT_SCHEMA")
    selector = env("DBT_SELECT")
    revision = env("GIT_REVISION")

    # Create the database if it doesn't exist
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

    # Run dbt as subprocess to avoid import issues
    result = subprocess.run(
        ["dbt", "build", "--select", selector,
         "--project-dir", project, "--profiles-dir", profiles, "--profile", "flight"],
        capture_output=True, text=True)

    print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)

    # Check run_results.json for summary
    run_results = os.path.join(project, "target", "run_results.json")
    if os.path.exists(run_results):
        with open(run_results) as handle:
            summary = json.load(handle)
        print("dbt nodes:", len(summary.get("results", [])),
              "elapsed:", summary.get("elapsed_time"))

    # Escalate failure
    if result.returncode != 0:
        print(f"dbt FAILED with exit code {result.returncode}", file=sys.stderr)
        sys.exit(1)
    print("dbt build succeeded for selector:", selector)


if __name__ == "__main__":
    main()
