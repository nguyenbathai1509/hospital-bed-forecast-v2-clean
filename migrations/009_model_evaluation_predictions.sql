/* V2-20A - Row-level evaluation evidence for Training visualizations.
   Stores immutable TEST predictions replayed from the original Training Run contract.
   This migration does NOT retrain Production artifacts and does NOT change Production.
*/

IF OBJECT_ID('dbo.model_evaluation_predictions', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.model_evaluation_predictions (
        candidate_id VARCHAR(80) NOT NULL,
        run_id VARCHAR(60) NOT NULL,
        horizon INT NOT NULL,
        model_family VARCHAR(20) NOT NULL,
        split_name VARCHAR(20) NOT NULL
            CONSTRAINT DF_model_eval_predictions_split DEFAULT ('TEST'),
        origin_date DATE NOT NULL,
        target_date DATE NOT NULL,
        department_id INT NOT NULL,
        actual_occupied_beds FLOAT NOT NULL,
        prediction_raw FLOAT NOT NULL,
        residual FLOAT NOT NULL,
        absolute_error FLOAT NOT NULL,
        feature_version VARCHAR(30) NOT NULL,
        data_version VARCHAR(100) NULL,
        replay_version VARCHAR(30) NOT NULL
            CONSTRAINT DF_model_eval_predictions_replay_version DEFAULT ('v2.0'),
        created_at DATETIME2(3) NOT NULL
            CONSTRAINT DF_model_eval_predictions_created DEFAULT SYSUTCDATETIME(),

        CONSTRAINT PK_model_evaluation_predictions
            PRIMARY KEY (candidate_id, origin_date, department_id),

        CONSTRAINT FK_model_eval_predictions_candidate
            FOREIGN KEY (candidate_id) REFERENCES dbo.model_candidates(candidate_id),

        CONSTRAINT FK_model_eval_predictions_training_run
            FOREIGN KEY (run_id) REFERENCES dbo.training_runs(run_id),

        CONSTRAINT FK_model_eval_predictions_department
            FOREIGN KEY (department_id) REFERENCES dbo.departments(department_id),

        CONSTRAINT CK_model_eval_predictions_horizon
            CHECK (horizon IN (1,3)),

        CONSTRAINT CK_model_eval_predictions_family
            CHECK (model_family IN ('RF','XGBOOST','SVR','LSTM')),

        CONSTRAINT CK_model_eval_predictions_split
            CHECK (split_name='TEST'),

        CONSTRAINT CK_model_eval_predictions_absolute_error
            CHECK (absolute_error >= 0),

        CONSTRAINT UQ_model_eval_predictions_target
            UNIQUE (candidate_id, target_date, department_id)
    );

    CREATE INDEX IX_model_eval_predictions_run_horizon_family
        ON dbo.model_evaluation_predictions(
            run_id, horizon, model_family, department_id, target_date
        );

    CREATE INDEX IX_model_eval_predictions_target_date
        ON dbo.model_evaluation_predictions(target_date, department_id);
END
GO