"""Benchmark suite for pyNMMS.

Run ``python -m bench`` (or ``make bench``) to execute every section and write
a JSON record to ``bench/results/``. ``--quick`` runs reduced sizes.

Sections:
    antecedent_scaling  query cost versus antecedent size |Γ| (issues 1-3)
    schema_scaling      axiom-check cost versus number of ontology schemas (issues 6-7)
    query_complexity    proof cost versus number of connectives in the query

The results directory is the regression baseline: compare a new record against
the most recent one for the same git SHA family before and after a change to
the reasoner or the base.
"""
