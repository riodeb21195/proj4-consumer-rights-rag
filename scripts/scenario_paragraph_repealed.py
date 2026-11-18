"""Scenario: a paragraph is repealed ("weggefallen") -> it disappears from the index."""

from _scenario import check, chunks, demo_pipeline, ingest, repeal, report

with demo_pipeline() as (pipeline, xml):
    report("initial ingest", ingest(pipeline))
    check(any(p == "§ 9" for p, _ in chunks(pipeline).values()), "§ 9 is indexed")

    repeal(xml, "§ 9")
    summary = ingest(pipeline)
    report("after repealing § 9", summary)
    check(summary.laws[0].norms_removed == 1, "one paragraph removed")
    check(all(p != "§ 9" for p, _ in chunks(pipeline).values()), "no chunk of § 9 left")
