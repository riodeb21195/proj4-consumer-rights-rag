"""Scenario: the same ingest runs twice -> no duplicates, nothing is rewritten."""

from _scenario import check, chunks, demo_pipeline, ingest, report

with demo_pipeline() as (pipeline, _xml):
    report("first ingest", ingest(pipeline))
    before = chunks(pipeline)
    summary = ingest(pipeline)
    report("second ingest", summary)
    check(summary.laws[0].status == "unchanged", "source recognised as unchanged")
    check(summary.laws[0].chunks_written == 0, "no chunk written")
    check(chunks(pipeline) == before, "identical chunk ids and hashes")
    versions = pipeline.store.law_versions("demo_pangv")
    check(len(versions) == 1, "one law version recorded")
