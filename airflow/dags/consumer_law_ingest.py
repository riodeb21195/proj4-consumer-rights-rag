"""Daily incremental ingest of German consumer-protection laws.

Every task runs the pipeline CLI in the separate RAG virtualenv baked into the image
(see airflow/Dockerfile), so Airflow and the ML stack never share dependencies.

check_sources -> ingest_<law> (one task per law, sequential to keep RAM low)

A failing law (e.g. broken XML) fails only its own task; the next laws still run
(trigger_rule=all_done) and the failure is visible in the Airflow UI and in ingest_runs.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG

RAG_PYTHON = "/opt/rag-venv/bin/python"
LAW_SLUGS = [s for s in os.environ.get("RAG_LAW_SLUGS", "").split(",") if s] or [
    "bgb",
    "evo_2023",
    "pangv_2022",
    "enwg_2005",
    "tkg_2021",
]

with DAG(
    dag_id="consumer_law_ingest",
    description="Incremental ingest of consumer-protection laws from gesetze-im-internet.de",
    schedule="@daily",
    start_date=datetime(2026, 11, 1),
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 1, "retry_delay": timedelta(minutes=5)},
    tags=["rag", "ingest"],
) as dag:
    check_sources = BashOperator(
        task_id="check_sources",
        bash_command=f"{RAG_PYTHON} -m rag.ingest.discover",
        append_env=True,
    )

    previous = check_sources
    for slug in LAW_SLUGS:
        ingest = BashOperator(
            task_id=f"ingest_{slug}",
            bash_command=(
                f"{RAG_PYTHON} -m rag.ingest.pipeline --laws {slug} "
                "--trigger 'airflow:{{ run_id }}'"
            ),
            append_env=True,
            trigger_rule="all_done",
            execution_timeout=timedelta(hours=1),
        )
        previous >> ingest
        previous = ingest
