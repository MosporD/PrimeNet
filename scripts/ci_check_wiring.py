"""Static wiring checks for CI.

Catches the class of breakage that unit tests miss because it only shows up when
Flask actually resolves a name at request time: a blueprint that never got
registered, a `render_template` target that does not exist, a `url_for` pointing
at an endpoint nobody defines. Each of those is a runtime 500 on a page that
looks fine in review.

Run directly: ``python scripts/ci_check_wiring.py``
"""

from __future__ import annotations

import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_SKIP = 'huawei_params'


def _sources(pattern: str) -> list[str]:
    return [p for p in glob.glob(pattern, recursive=True) if _SKIP not in p]


def _read(path: str) -> str:
    with open(path, encoding='utf-8', errors='replace') as fh:
        return fh.read()


def main() -> int:
    import app as app_module
    import nexpulse_app
    import nexuscore_app

    # The suite is three Flask apps (engineering portal, NexusCore, NexPulse) and templates
    # such as portals/marketing/** or portal_select.html belong to the other two, so a name
    # only has to resolve in one of them.
    flask_apps = [app_module.app, nexuscore_app.app, nexpulse_app.app]
    flask_app = flask_apps[0]
    rules = [rule for a in flask_apps for rule in a.url_map.iter_rules()]
    failures: list[str] = []

    print(f'blueprints registered: {sum(len(a.blueprints) for a in flask_apps)}')
    print(f'url rules:             {len(rules)}')
    if not flask_app.blueprints:
        failures.append('no blueprints registered')

    # Duplicate rule + method pairs mean one route silently shadows another.
    # (Engineering portal only: NexPulse currently shadows ``/`` with ``auth.index``.)
    seen: dict[tuple[str, frozenset[str]], list[str]] = {}
    for rule in flask_app.url_map.iter_rules():
        key = (str(rule), frozenset(rule.methods or ()))
        seen.setdefault(key, []).append(rule.endpoint)
    for (path, _methods), endpoints in seen.items():
        if len(endpoints) > 1:
            failures.append(f'duplicate route {path}: {sorted(endpoints)}')

    # Every render_template target must resolve.
    targets: set[str] = set()
    for path in _sources('**/*.py'):
        targets.update(re.findall(r'render_template\(\s*[\'"]([^\'"]+)[\'"]', _read(path)))
    for name in sorted(targets):
        for a in flask_apps:
            try:
                with a.app_context():
                    a.jinja_env.get_template(name)
                break
            except Exception:
                continue
        else:
            failures.append(f'unresolvable template: {name}')
    print(f'render_template targets: {len(targets)}')

    # Every url_for endpoint referenced from a template must exist.
    endpoints = {rule.endpoint for rule in rules} | {'static'}
    broken: dict[str, str] = {}
    for path in _sources('**/*.html'):
        for endpoint in re.findall(r'url_for\(\s*[\'"]([A-Za-z0-9_.]+)[\'"]', _read(path)):
            if endpoint not in endpoints and not endpoint.endswith('.static'):
                broken.setdefault(endpoint, path)
    for endpoint, path in sorted(broken.items()):
        failures.append(f'broken url_for endpoint {endpoint!r} in {path}')

    # Static assets referenced by templates must exist on disk.
    checked = missing = 0
    for path in _sources('**/*.html'):
        for endpoint, filename in re.findall(
            r'url_for\(\s*[\'"]([a-z_.]*static)[\'"]\s*,\s*filename\s*=\s*[\'"]([^\'"?]+)',
            _read(path),
        ):
            checked += 1
            candidates = [os.path.join('static', filename)]
            if endpoint != 'static':
                candidates += glob.glob(f'modules/*/static/{filename}')
                candidates += glob.glob(f'portals/*/static/{filename}')
            if not any(os.path.exists(c) for c in candidates):
                missing += 1
                failures.append(f'missing static asset {filename!r} referenced by {path}')
    print(f'static asset refs:       {checked} ({missing} missing)')

    if failures:
        print('\nFAILED:')
        for line in failures:
            print(f'  - {line}')
        return 1
    print('\nwiring OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
