"""Intelligence layer: recommendation synthesis, explainers, AI analysis.

Pure-Python orchestration around the analysis engines in
:mod:`backend.app.analysis`. This package must not import API or DB models
at module top level to keep it cheap to import inside Celery workers.
"""
