"""Daily reconciliation + compliance run for one brokerage tenant.

Extract (broker adapter) -> analyze (LedgerGuard engine) -> load (store).
Runs after the T+1 settlement files land. Swap SyntheticAdapter for your
broker's adapter / CsvAdapter pointed at the SFTP drop.
"""
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

from ledgerguard import engine
from ledgerguard.adapters import CsvAdapter
from ledgerguard.store import Store

DROP_DIR = "/data/broker_exports"
DB_PATH = "/data/ledgerguard.db"
TENANT = "acme-brokerage"


def analyze(ds_nodash: str, **_):
    as_of = datetime.strptime(ds_nodash, "%Y%m%d").date()
    report = engine.run(CsvAdapter(DROP_DIR).fetch(TENANT, as_of))
    run_id = Store(DB_PATH).save_report(TENANT, report)
    if report["by_severity"].get("critical"):
        raise RuntimeError(f"run {run_id}: {report['by_severity']['critical']} critical compliance alerts")
    return run_id


with DAG(
    "ledgerguard_daily",
    start_date=datetime(2026, 1, 1),
    schedule="0 6 * * 2-6",  # after prior-day T+1 settlement
    catchup=False,
    default_args={"retries": 2, "retry_delay": timedelta(minutes=10)},
) as dag:
    PythonOperator(task_id="reconcile_and_screen", python_callable=analyze)
