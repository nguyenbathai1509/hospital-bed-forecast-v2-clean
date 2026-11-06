from pathlib import Path


def test_evaluation_prediction_migration_is_immutable_test_evidence_contract():
    root = Path(__file__).resolve().parents[1]
    sql = (root / "migrations" / "009_model_evaluation_predictions.sql").read_text(
        encoding="utf-8"
    )

    assert "dbo.model_evaluation_predictions" in sql
    assert "actual_occupied_beds" in sql
    assert "prediction_raw" in sql
    assert "residual" in sql
    assert "absolute_error" in sql
    assert "CHECK (split_name='TEST')" in sql
    assert "FK_model_eval_predictions_candidate" in sql
    assert "FK_model_eval_predictions_training_run" in sql
    assert "FK_model_eval_predictions_department" in sql
    assert "UNIQUE (candidate_id, target_date, department_id)" in sql