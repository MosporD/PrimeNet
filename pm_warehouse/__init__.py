"""
PM warehouse pilot: raw NBI counter ingestion + aggregation in PostgreSQL.

Store counters, aggregate counters (time-wise and object-wise), apply KPI
formulas at query time. See pm_warehouse/README.md for the design summary and
docs/course-level detail in the session design doc.

Standalone by design: importable and runnable without the Flask app.
"""
