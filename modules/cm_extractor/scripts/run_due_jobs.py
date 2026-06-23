"""Run all due CM Extractor scheduled jobs once (same as the 1-minute dispatcher tick)."""

from __future__ import annotations

from modules.cm_extractor.scripts._bootstrap import bootstrap

bootstrap()

from core.cm_extractor.job_scheduler import run_due_jobs


def main() -> int:
    count = run_due_jobs()
    print(f'Executed {count} CM Extractor scheduled job(s).')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
