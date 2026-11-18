"""Scenario: a law is amended -> only the affected chunks are re-embedded, the rest is untouched."""

from _scenario import amend, check, chunks, demo_pipeline, ingest, report

with demo_pipeline() as (pipeline, xml):
    report("initial ingest", ingest(pipeline))
    before = chunks(pipeline)

    amend(xml, "§ 4", "Grundpreis", "Grundpreis (geändert)")
    summary = ingest(pipeline)
    report("after amending § 4", summary)
    after = chunks(pipeline)

    untouched = {cid for cid, (para, _) in before.items() if para != "§ 4"}
    check(summary.laws[0].norms_changed == 1, "exactly one paragraph detected as changed")
    check(untouched <= set(after), "all chunks of other paragraphs kept their ids")
    check(all(after[c] == before[c] for c in untouched), "and their content hashes")
    new_ids = set(after) - set(before)
    check(bool(new_ids) and {after[c][0] for c in new_ids} == {"§ 4"}, "new chunks only for § 4")
