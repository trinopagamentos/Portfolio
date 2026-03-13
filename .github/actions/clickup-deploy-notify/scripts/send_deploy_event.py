#!/usr/bin/env python3
import hashlib
import hmac
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def parse_json(value: str, default):
    if not value:
        return default
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, type(default)) else default
    except json.JSONDecodeError:
        return default


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_event_payload() -> dict:
    path = env("GITHUB_EVENT_PATH")
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return {}


def git_commit_message() -> str:
    if not os.path.isdir(".git"):
        return ""
    try:
        return (
            subprocess.check_output(["git", "log", "-1", "--pretty=%s"], stderr=subprocess.DEVNULL)
            .decode("utf-8", errors="ignore")
            .strip()
        )
    except Exception:
        return ""


def derive_status(event_type: str, requested_status: str, job_result: str) -> str:
    if requested_status:
        return requested_status
    if event_type == "deploy_started":
        return "started"
    result = (job_result or "").lower()
    if result == "success":
        return "success"
    if result == "cancelled":
        return "cancelled"
    return "failure"


def infer_failure_stage(gates: dict, explicit_stage: str, fallback_stage: str) -> str:
    if explicit_stage:
        return explicit_stage
    for name, result in gates.items():
        if str(result).lower() in {"failure", "cancelled", "timed_out"}:
            return str(name)
    return fallback_stage or "deploy"


def duration_seconds(started_at: str, completed_at: str):
    if not started_at or not completed_at:
        return None
    try:
        start_dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
        return max(0, int((end_dt - start_dt).total_seconds()))
    except ValueError:
        return None


def build_payload() -> tuple[dict, str]:
    event_data = read_event_payload()
    event_type = env("INPUT_EVENT_TYPE")
    observed_at = env("INPUT_COMPLETED_AT") or now_iso()
    started_at = env("INPUT_STARTED_AT")
    completed_at = env("INPUT_COMPLETED_AT") or (observed_at if event_type == "deploy_finished" else "")
    gates = parse_json(env("INPUT_GATES_JSON", "{}"), {})
    metadata = parse_json(env("INPUT_METADATA_JSON", "{}"), {})
    status = derive_status(event_type, env("INPUT_STATUS"), env("INPUT_JOB_RESULT"))

    repository = env("GITHUB_REPOSITORY")
    run_id = env("GITHUB_RUN_ID")
    run_attempt = env("GITHUB_RUN_ATTEMPT", "1")
    run_url = f"{env('GITHUB_SERVER_URL', 'https://github.com')}/{repository}/actions/runs/{run_id}"
    sha = env("GITHUB_SHA")
    branch = env("GITHUB_HEAD_REF") or env("GITHUB_REF_NAME")

    pull_request = event_data.get("pull_request") or {}
    pr_number = pull_request.get("number")
    if not pr_number and isinstance(event_data.get("number"), int):
        pr_number = event_data.get("number")

    payload = {
        "version": "1.0",
        "source": "github_actions",
        "event_type": event_type,
        "status": status,
        "application": env("INPUT_APPLICATION"),
        "environment": env("INPUT_ENVIRONMENT", "production"),
        "observed_at_utc": observed_at,
        "workflow": {
            "repository": repository,
            "workflow_name": env("GITHUB_WORKFLOW"),
            "job_name": env("INPUT_JOB_NAME") or env("GITHUB_JOB"),
            "run_id": run_id,
            "run_attempt": int(run_attempt or "1"),
            "run_number": env("GITHUB_RUN_NUMBER"),
            "run_url": run_url,
            "actor": env("GITHUB_ACTOR"),
            "event_name": env("GITHUB_EVENT_NAME"),
            "ref": env("GITHUB_REF"),
            "ref_name": env("GITHUB_REF_NAME"),
            "head_ref": env("GITHUB_HEAD_REF"),
            "base_ref": env("GITHUB_BASE_REF"),
            "server_url": env("GITHUB_SERVER_URL", "https://github.com"),
        },
        "git": {
            "sha": sha,
            "short_sha": sha[:8] if sha else "",
            "branch": branch,
            "message": git_commit_message() or (((event_data.get("head_commit") or {}).get("message")) or ""),
        },
        "pull_request": {
            "number": pr_number or "",
            "title": pull_request.get("title", ""),
            "url": pull_request.get("html_url", ""),
            "merged": bool(pull_request.get("merged", False)),
            "review_state": ((event_data.get("review") or {}).get("state")) or "",
        },
        "timing": {
            "started_at_utc": started_at,
            "completed_at_utc": completed_at,
            "duration_seconds": duration_seconds(started_at, completed_at),
        },
        "deployment": {
            "stage": env("INPUT_STAGE"),
            "target_type": env("INPUT_TARGET_TYPE"),
            "target_name": env("INPUT_TARGET_NAME"),
            "workflow_pattern": env("INPUT_WORKFLOW_PATTERN"),
            "cleanup_status": env("INPUT_CLEANUP_STATUS"),
            "rollback_status": env("INPUT_ROLLBACK_STATUS"),
        },
        "gates": gates,
        "failure": {
            "stage": infer_failure_stage(gates, env("INPUT_FAILURE_STAGE"), env("INPUT_STAGE")),
            "summary": env("INPUT_FAILURE_SUMMARY"),
        },
        "metadata": metadata,
    }

    payload["event_id"] = hashlib.sha256(
        "|".join(
            [
                payload["workflow"]["repository"],
                str(payload["workflow"]["run_id"]),
                str(payload["workflow"]["run_attempt"]),
                payload["workflow"]["job_name"],
                payload["event_type"],
                payload["status"],
                payload["application"],
            ]
        ).encode("utf-8")
    ).hexdigest()

    return payload, observed_at


def write_output(name: str, value: str) -> None:
    output_path = env("GITHUB_OUTPUT")
    if not output_path:
        return
    with open(output_path, "a", encoding="utf-8") as handle:
        handle.write(f"{name}={value}\n")


def post_payload(payload: dict) -> tuple[str, str]:
    relay_url = env("INPUT_RELAY_URL")
    secret = env("INPUT_RELAY_SHARED_SECRET")

    if not relay_url or not secret:
        print("::warning::Deploy relay not configured. Skipping ClickUp notification.")
        return "skipped", ""

    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(time.time()))
    signature = "sha256=" + hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.{body.decode('utf-8')}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    request = urllib.request.Request(
        relay_url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Deploy-Timestamp": timestamp,
            "X-Deploy-Signature": signature,
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            status_code = response.getcode()
            response_body = response.read().decode("utf-8", errors="ignore")
            if 200 <= status_code < 300:
                print(f"Relay accepted deploy event ({status_code}).")
                return "sent", response_body
            print(f"::warning::Relay returned HTTP {status_code}: {response_body}")
            return "failed", response_body
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="ignore")
        print(f"::warning::Relay HTTP error {exc.code}: {body_text}")
        return "failed", body_text
    except Exception as exc:  # pragma: no cover - network level
        print(f"::warning::Relay request failed: {exc}")
        return "failed", str(exc)


def main() -> int:
    payload, observed_at = build_payload()
    delivery_status, _ = post_payload(payload)
    write_output("event_timestamp", observed_at)
    write_output("delivery_status", delivery_status)
    return 0


if __name__ == "__main__":
    sys.exit(main())
