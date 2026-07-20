"""
Post-deploy smoke test — validates a running instance in seconds.

    python -m scripts.smoke_test                       # http://localhost:8000
    python -m scripts.smoke_test https://ajoda.app     # a deployed instance
    SMOKE_BASE_URL=https://ajoda.app python -m scripts.smoke_test

Checks the health probe (with its DB report) and that the API is serving. Uses
only httpx + stdlib, so it runs against a remote deploy without the app's .env.
Exits non-zero if any check fails, so it drops straight into a deploy pipeline.
"""
import os
import sys

import httpx

TIMEOUT = 10.0


def _base_url() -> str:
    if len(sys.argv) > 1 and sys.argv[1].startswith("http"):
        return sys.argv[1].rstrip("/")
    return os.environ.get("SMOKE_BASE_URL", "http://localhost:8000").rstrip("/")


def main() -> int:
    base = _base_url()
    print(f"Smoke testing {base}")
    failures = 0

    with httpx.Client(timeout=TIMEOUT) as client:
        # 1) Health probe — must be 200 and report the database reachable.
        try:
            r = client.get(f"{base}/health")
            body = r.json()
            if r.status_code == 200 and body.get("database") == "ok":
                print(f"  PASS  health — status={body.get('status')} db={body.get('database')}")
            else:
                failures += 1
                print(f"  FAIL  health — {r.status_code} {body}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"  FAIL  health — {exc}")

        # 2) API is serving (OpenAPI schema renders).
        try:
            r = client.get(f"{base}/openapi.json")
            ok = r.status_code == 200 and r.json().get("info", {}).get("title") == "Ajoda"
            print(("  PASS  api — openapi served" if ok else f"  FAIL  api — {r.status_code}"))
            failures += 0 if ok else 1
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"  FAIL  api — {exc}")

        # 3) An unauthenticated protected route must reject (auth wired), not 500.
        try:
            r = client.get(f"{base}/api/cooperatives")
            ok = r.status_code in (401, 403)
            print(("  PASS  auth — protected route rejects anonymous"
                   if ok else f"  FAIL  auth — expected 401/403, got {r.status_code}"))
            failures += 0 if ok else 1
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"  FAIL  auth — {exc}")

    if failures:
        print(f"\n{failures} check(s) failed.")
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
