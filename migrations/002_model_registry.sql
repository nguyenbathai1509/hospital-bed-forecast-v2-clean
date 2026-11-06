/* V2-13 - Model Registry foundation
   Adds versioned training/model metadata and production slots.
   This migration does NOT train models and does NOT promote anything automatically.
*/

IF OBJECT_ID('dbo.training_runs', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.training_runs (
        run_id VARCHAR(60) NOT NULL CONSTRAINT PK_training_runs PRIMARY KEY,
        business_date DATE NOT NULL,
        status VARCHAR(20) NOT NULL,
        triggered_by NVARCHAR(100) NULL,
        scope VARCHAR(20) NOT NULL CONSTRAINT DF_training_runs_scope DEFAULT ('GLOBAL'),
        data_start DATE NULL,
        data_end DATE NULL,
        data_version VARCHAR(100) NULL,
        feature_version VARCHAR(30) NOT NULL,
        feature_hash CHAR(64) NULL,
        row_count INT NULL,
        department_count INT NULL,
        split_spec_json NVARCHAR(MAX) NULL,
        algorithm_set_json NVARCHAR(MAX) NULL,
        started_at DATETIME2(3) NOT NULL
            CONSTRAINT DF_training_runs_started DEFAULT SYSUTCDATETIME(),
        completed_at DATETIME2(3) NULL,
        error_message NVARCHAR(MAX) NULL,

        CONSTRAINT CK_training_runs_status
            CHECK (status IN ('PENDING','RUNNING','COMPLETED','FAILED')),

        CONSTRAINT CK_training_runs_scope
            CHECK (scope IN ('GLOBAL','LOCAL')),

        CONSTRAINT CK_training_runs_counts CHECK (
            (row_count IS NULL OR row_count >= 0)
            AND
            (department_count IS NULL OR department_count >= 0)
        )
    );

    CREATE INDEX IX_training_runs_status_date
        ON dbo.training_runs(status, business_date);

    CREATE UNIQUE INDEX UX_training_runs_one_completed_per_business_date
        ON dbo.training_runs(business_date)
        WHERE status = 'COMPLETED';
END
GO


IF OBJECT_ID('dbo.model_candidates', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.model_candidates (
        candidate_id VARCHAR(80) NOT NULL
            CONSTRAINT PK_model_candidates PRIMARY KEY,

        run_id VARCHAR(60) NOT NULL,
        horizon INT NOT NULL,
        model_family VARCHAR(20) NOT NULL,

        scope VARCHAR(20) NOT NULL
            CONSTRAINT DF_model_candidates_scope DEFAULT ('GLOBAL'),

        registry_status VARCHAR(20) NOT NULL
            CONSTRAINT DF_model_candidates_status DEFAULT ('CANDIDATE'),

        is_recommended BIT NOT NULL
            CONSTRAINT DF_model_candidates_recommended DEFAULT (0),

        artifact_path NVARCHAR(1000) NOT NULL,
        artifact_type VARCHAR(30) NOT NULL,
        inference_type VARCHAR(30) NOT NULL,
        artifact_sha256 CHAR(64) NULL,

        feature_version VARCHAR(30) NOT NULL,
        data_version VARCHAR(100) NULL,

        feature_order_json NVARCHAR(MAX) NULL,
        model_metadata_json NVARCHAR(MAX) NULL,
        best_params_json NVARCHAR(MAX) NULL,

        mae FLOAT NULL,
        rmse FLOAT NULL,
        wape FLOAT NULL,
        r2 FLOAT NULL,
        bias FLOAT NULL,

        p90_abs_error FLOAT NULL,
        max_abs_error FLOAT NULL,
        within_2_rate FLOAT NULL,
        underprediction_rate FLOAT NULL,
        underprediction_mae FLOAT NULL,

        created_at DATETIME2(3) NOT NULL
            CONSTRAINT DF_model_candidates_created DEFAULT SYSUTCDATETIME(),

        updated_at DATETIME2(3) NULL,

        CONSTRAINT FK_model_candidates_training_run
            FOREIGN KEY (run_id)
            REFERENCES dbo.training_runs(run_id),

        CONSTRAINT CK_model_candidates_horizon
            CHECK (horizon IN (1,3)),

        CONSTRAINT CK_model_candidates_family
            CHECK (model_family IN ('RF','XGBOOST','SVR','LSTM')),

        CONSTRAINT CK_model_candidates_scope
            CHECK (scope IN ('GLOBAL','LOCAL')),

        CONSTRAINT CK_model_candidates_status CHECK (
            registry_status IN (
                'CANDIDATE',
                'RECOMMENDED',
                'PRODUCTION',
                'SCHEDULED',
                'ARCHIVED',
                'FAILED'
            )
        ),

        CONSTRAINT CK_model_candidates_artifact_type CHECK (
            artifact_type IN (
                'SKLEARN_JOBLIB',
                'KERAS_BUNDLE'
            )
        ),

        CONSTRAINT CK_model_candidates_inference_type CHECK (
            inference_type IN (
                'TABULAR_28',
                'SEQUENCE_3X12'
            )
        ),

        CONSTRAINT CK_model_candidates_metric_nonnegative CHECK (
            (mae IS NULL OR mae >= 0)
            AND
            (rmse IS NULL OR rmse >= 0)
            AND
            (wape IS NULL OR wape >= 0)
            AND
            (p90_abs_error IS NULL OR p90_abs_error >= 0)
            AND
            (max_abs_error IS NULL OR max_abs_error >= 0)
            AND
            (
                within_2_rate IS NULL
                OR
                (within_2_rate >= 0 AND within_2_rate <= 1)
            )
            AND
            (
                underprediction_rate IS NULL
                OR
                (
                    underprediction_rate >= 0
                    AND
                    underprediction_rate <= 1
                )
            )
            AND
            (
                underprediction_mae IS NULL
                OR underprediction_mae >= 0
            )
        ),

        CONSTRAINT CK_model_candidates_family_artifact_contract CHECK (
            (
                model_family = 'LSTM'
                AND artifact_type = 'KERAS_BUNDLE'
                AND inference_type = 'SEQUENCE_3X12'
            )
            OR
            (
                model_family IN ('RF','XGBOOST','SVR')
                AND artifact_type = 'SKLEARN_JOBLIB'
                AND inference_type = 'TABULAR_28'
            )
        ),

        CONSTRAINT UQ_model_candidate_id_horizon
            UNIQUE (candidate_id, horizon),

        CONSTRAINT UQ_model_candidate_run_horizon_family
            UNIQUE (run_id, horizon, model_family)
    );

    CREATE INDEX IX_model_candidates_horizon_status
        ON dbo.model_candidates(horizon, registry_status);

    CREATE INDEX IX_model_candidates_run_horizon
        ON dbo.model_candidates(run_id, horizon);
END
GO


IF OBJECT_ID('dbo.model_metrics_by_department', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.model_metrics_by_department (
        candidate_id VARCHAR(80) NOT NULL,
        department_id INT NOT NULL,

        sample_count INT NOT NULL,

        mae FLOAT NOT NULL,
        rmse FLOAT NOT NULL,
        wape FLOAT NOT NULL,
        r2 FLOAT NULL,
        bias FLOAT NOT NULL,

        p90_abs_error FLOAT NULL,
        max_abs_error FLOAT NOT NULL,
        within_2_rate FLOAT NULL,
        underprediction_rate FLOAT NULL,
        underprediction_mae FLOAT NULL,

        created_at DATETIME2(3) NOT NULL
            CONSTRAINT DF_model_metrics_department_created
            DEFAULT SYSUTCDATETIME(),

        CONSTRAINT PK_model_metrics_by_department
            PRIMARY KEY (candidate_id, department_id),

        CONSTRAINT FK_model_metrics_candidate
            FOREIGN KEY (candidate_id)
            REFERENCES dbo.model_candidates(candidate_id),

        CONSTRAINT FK_model_metrics_department
            FOREIGN KEY (department_id)
            REFERENCES dbo.departments(department_id),

        CONSTRAINT CK_model_metrics_sample_count
            CHECK (sample_count > 0),

        CONSTRAINT CK_model_metrics_nonnegative CHECK (
            mae >= 0
            AND rmse >= 0
            AND wape >= 0
            AND max_abs_error >= 0
            AND
            (p90_abs_error IS NULL OR p90_abs_error >= 0)
            AND
            (
                within_2_rate IS NULL
                OR
                (within_2_rate >= 0 AND within_2_rate <= 1)
            )
            AND
            (
                underprediction_rate IS NULL
                OR
                (
                    underprediction_rate >= 0
                    AND
                    underprediction_rate <= 1
                )
            )
            AND
            (
                underprediction_mae IS NULL
                OR underprediction_mae >= 0
            )
        )
    );

    CREATE INDEX IX_model_metrics_department
        ON dbo.model_metrics_by_department(
            department_id,
            candidate_id
        );
END
GO


IF OBJECT_ID('dbo.production_models', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.production_models (
        production_id BIGINT IDENTITY(1,1) NOT NULL
            CONSTRAINT PK_production_models PRIMARY KEY,

        horizon INT NOT NULL,
        candidate_id VARCHAR(80) NOT NULL,

        slot_status VARCHAR(20) NOT NULL,

        effective_from_business_date DATE NOT NULL,
        effective_to_business_date DATE NULL,

        promoted_by NVARCHAR(100) NULL,
        promotion_reason NVARCHAR(1000) NULL,

        created_at DATETIME2(3) NOT NULL
            CONSTRAINT DF_production_models_created
            DEFAULT SYSUTCDATETIME(),

        CONSTRAINT FK_production_models_candidate_horizon
            FOREIGN KEY (candidate_id, horizon)
            REFERENCES dbo.model_candidates(candidate_id, horizon),

        CONSTRAINT CK_production_models_horizon
            CHECK (horizon IN (1,3)),

        CONSTRAINT CK_production_models_status
            CHECK (
                slot_status IN (
                    'ACTIVE',
                    'SCHEDULED',
                    'RETIRED'
                )
            ),

        CONSTRAINT CK_production_models_dates CHECK (
            effective_to_business_date IS NULL
            OR
            effective_to_business_date
                >= effective_from_business_date
        )
    );

    CREATE UNIQUE INDEX UX_production_models_one_active_per_horizon
        ON dbo.production_models(horizon)
        WHERE slot_status = 'ACTIVE';

    CREATE UNIQUE INDEX UX_production_models_one_scheduled_per_horizon
        ON dbo.production_models(horizon)
        WHERE slot_status = 'SCHEDULED';

    CREATE INDEX IX_production_models_candidate
        ON dbo.production_models(
            candidate_id,
            slot_status
        );
END
GO