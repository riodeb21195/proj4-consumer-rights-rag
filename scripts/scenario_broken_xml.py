"""Scenario: a broken XML file -> skipped and reported, the indexed version stays searchable."""

from _scenario import check, chunks, demo_pipeline, ingest, report

with demo_pipeline() as (pipeline, xml):
    report("initial ingest", ingest(pipeline))
    before = chunks(pipeline)

    xml.write_bytes(xml.read_bytes()[:5000])  # truncated download
    summary = ingest(pipeline)
    report("after corrupting the XML", summary)
    run = pipeline.store.get_run(summary.run_id)
    check(summary.laws[0].status == "failed", "law marked as failed")
    check(
        run is not None and run["errors"][0]["law"] == "demo_pangv", "error stored in ingest_runs"
    )
    check(chunks(pipeline) == before, "previous chunks are still indexed (transaction rolled back)")
