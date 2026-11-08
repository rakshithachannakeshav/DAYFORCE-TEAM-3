import tempfile
from pathlib import Path

from db import (
    get_generation_history,
    get_generation_run,
    init_db,
    save_generation_run,
    save_requirement,
)
from generator import generate_baseline_test_suite
from schemas import Priority, Requirement


def test_db_lifecycle_in_isolated_file():
    with tempfile.TemporaryDirectory() as temp_dir:
        test_db_path = Path(temp_dir) / "test.db"

        # 1. Initialize
        init_db(test_db_path)
        assert test_db_path.exists()

        # 2. Save Requirement
        req = Requirement(
            id="REQ-TEST-SQL",
            title="Database test",
            description="Testing SQLite storage",
            actor="Tester",
            rules=["Rule 1", "Rule 2"],
            priority=Priority.high,
        )
        save_requirement(req, test_db_path)

        # 3. Save Generation Run
        gen_result = generate_baseline_test_suite(req)
        run_id = save_generation_run(gen_result, test_db_path)
        assert run_id >= 1

        # 4. Retrieve History
        history = get_generation_history(limit=5, db_path=test_db_path)
        assert len(history) == 1
        assert history[0]["requirement_id"] == "REQ-TEST-SQL"
        assert history[0]["requirement_title"] == "Database test"

        # 5. Retrieve Specific Run
        fetched = get_generation_run(run_id, test_db_path)
        assert fetched is not None
        assert fetched.requirement_id == "REQ-TEST-SQL"
        assert len(fetched.traceability) == 2

        # 6. Nonexistent run returns None
        assert get_generation_run(8888, test_db_path) is None

