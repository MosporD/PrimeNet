"""NexusCore portals.

Each sub-package is a self-contained portal application under the NexusCore
umbrella. A portal owns its own data store, templates, static assets, and
access rules, and never imports from ``modules/`` (PrimeNet's Engineering
Portal) or reads another portal's database directly.

See ``docs/NEXUSCORE_VISION.md`` for the architecture rules.
"""
