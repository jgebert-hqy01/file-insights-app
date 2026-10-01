"""Pure import-only preflight check: no network calls, no Databricks
connection. Reports which of the app's real dependencies actually import
on this machine, and why not if they don't -- e.g. an endpoint Application
Control policy blocking a compiled extension, which has happened before on
this project (numpy, pydantic_core).

Run this before scripts/connect_check.py. If imports are blocked here,
connect_check.py can't work either -- that's a local-machine/IT policy
question, not a bug in this repo, and the same checks still work in
Codespaces with the same environment variables.

Usage:
    python scripts/preflight.py
"""
import importlib
import sys

_MODULES_TO_CHECK = ("pydantic", "pandas", "pyarrow", "databricks.sql")


def check_import(module_name):
    try:
        importlib.import_module(module_name)
    except Exception as exc:  # noqa: BLE001 -- reporting only, not handling
        return False, "{0}: {1}".format(type(exc).__name__, exc)
    return True, ""


def main():
    results = []
    for module_name in _MODULES_TO_CHECK:
        ok, reason = check_import(module_name)
        results.append((module_name, ok, reason))
        status = "PASS" if ok else "FAIL"
        print("[{0}] {1}{2}".format(status, module_name, "" if ok else " -- " + reason))

    failures = [name for name, ok, _reason in results if not ok]
    print()
    if failures:
        print(
            "{0} of {1} import(s) failed: {2}".format(
                len(failures), len(results), ", ".join(failures)
            )
        )
        print(
            "If a failure mentions a blocked file or an Application Control "
            "policy, that's a local-machine/IT policy question -- stop here "
            "rather than trying to work around it. connect_check.py will hit "
            "the same wall. The same checks still work from an environment "
            "without that restriction (e.g. Codespaces), using the same "
            "environment variables."
        )
        return 1
    print("All imports OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
