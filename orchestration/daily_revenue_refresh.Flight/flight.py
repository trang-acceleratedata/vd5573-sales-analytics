import os
import subprocess
import sys


def main():
    """
    Run dbt build to refresh raw_orders seed and daily_revenue model daily at 6am UTC.
    """
    # Read configuration from environment
    git_repo = os.environ.get("GIT_REPO", "").strip()
    git_revision = os.environ.get("GIT_REVISION", "").strip()
    motherduck_token = os.environ.get("MOTHERDUCK_TOKEN", "").strip()
    destination_db = os.environ.get("DESTINATION_DATABASE", "").strip()

    if not all([git_repo, git_revision, motherduck_token, destination_db]):
        print("ERROR: Missing required environment variables")
        sys.exit(1)

    # Set up dbt environment
    os.environ["DBT_MOTHERDUCK_TOKEN"] = motherduck_token
    os.environ["DBT_MOTHERDUCK_DATABASE"] = destination_db

    # Clone repo
    print(f"Cloning {git_repo} at {git_revision}...")
    result = subprocess.run(
        ["git", "clone", git_repo, "/tmp/repo"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"ERROR: Git clone failed: {result.stderr}")
        sys.exit(1)

    # Checkout revision
    result = subprocess.run(
        ["git", "checkout", git_revision],
        cwd="/tmp/repo",
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"ERROR: Git checkout failed: {result.stderr}")
        sys.exit(1)

    # Run dbt build
    print("Running dbt build...")
    result = subprocess.run(
        ["dbt", "build"],
        cwd="/tmp/repo/transformation",
        capture_output=True,
        text=True,
    )
    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr)

    if result.returncode != 0:
        print(f"ERROR: dbt build failed with exit code {result.returncode}")
        sys.exit(1)

    print("Daily revenue refresh completed successfully")


if __name__ == "__main__":
    main()
