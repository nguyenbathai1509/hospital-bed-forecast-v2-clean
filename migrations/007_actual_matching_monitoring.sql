/* V2-18 - Actual Matching + Production Monitoring.
   Only immutable Official Forecasts are eligible for matching and monitoring.
   Actual is attached from dbo.clean_bed_daily by target_date + department_id.
   Future Actual is never fabricated: Official rows remain waiting until CLEAN reaches
   their target date. Monitoring snapshots use prediction_raw for model-quality metrics.
*/

IF OBJECT_ID('dbo.official_actual_matches', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.official_actual_matches (
        official_id VARCHAR(90) NOT NULL
            CONSTRAINT PK_official_actual_matches PRIMARY KEY,

        origin_date DATE NOT NULL,
        target_date DATE NOT NULL,
        department_id INT NOT NULL,
        horizon INT NOT NULL,
        candidate_id VARCHAR(80) NOT NULL,

        planned_beds INT NOT NULL,
        prediction_raw FLOAT NOT NULL,
        prediction_rounded INT NOT NULL,
        capacity_alert BIT NOT NULL,

        actual_occupied_beds INT NOT NULL,
        actual_quality_flag VARCHAR(10) NOT NULL,
        actual_source_revision_no INT NOT NULL,

        error_raw FLOAT NOT NULL,
        abs_error_raw FLOAT NOT NULL,
        error_rounded INT NOT NULL,
        abs_error_rounded INT NOT NULL,
        underpredicted BIT NOT NULL,
        overpredicted BIT NOT NULL,
        exact_rounded BIT NOT NULL,

        actual_capacity_exceeded BIT NOT NULL,
        capacity_alert_correct BIT NOT NULL,

        match_revision_no INT NOT NULL
            CONSTRAINT DF_official_actual_matches_revision DEFAULT (1),
        first_matched_at DATETIME2(3) NOT NULL
            CONSTRAINT DF_official_actual_matches_first DEFAULT SYSUTCDATETIME(),
        last_refreshed_at DATETIME2(3) NOT NULL
            CONSTRAINT DF_official_actual_matches_last DEFAULT SYSUTCDATETIME(),

        CONSTRAINT FK_official_actual_matches_official
            FOREIGN KEY (official_id)
            REFERENCES dbo.official_forecasts(official_id),

        CONSTRAINT FK_official_actual_matches_department
            FOREIGN KEY (department_id)
            REFERENCES dbo.departments(department_id),

        CONSTRAINT FK_official_actual_matches_candidate_horizon
            FOREIGN KEY (candidate_id, horizon)
            REFERENCES dbo.model_candidates(candidate_id, horizon),

        CONSTRAINT CK_official_actual_matches_horizon
            CHECK (horizon IN (1,3)),

        CONSTRAINT CK_official_actual_matches_quality
            CHECK (actual_quality_flag IN ('PASS','WARNING','CHECK')),

        CONSTRAINT CK_official_actual_matches_values CHECK (
            planned_beds > 0
            AND prediction_rounded >= 0
            AND actual_occupied_beds >= 0
            AND actual_source_revision_no >= 1
            AND abs_error_raw >= 0
            AND abs_error_rounded >= 0
            AND match_revision_no >= 1
        ),

        CONSTRAINT CK_official_actual_matches_target_date
            CHECK (target_date=DATEADD(DAY, horizon, origin_date))
    );

    CREATE INDEX IX_official_actual_matches_target
        ON dbo.official_actual_matches(target_date, department_id, horizon);

    CREATE INDEX IX_official_actual_matches_candidate
        ON dbo.official_actual_matches(candidate_id, horizon, target_date);
END
GO

IF OBJECT_ID('dbo.production_monitoring_runs', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.production_monitoring_runs (
        monitoring_run_id VARCHAR(90) NOT NULL
            CONSTRAINT PK_production_monitoring_runs PRIMARY KEY,

        pipeline_run_id VARCHAR(60) NOT NULL,
        business_date DATE NOT NULL,
        latest_actual_date DATE NULL,
        status VARCHAR(30) NOT NULL,

        official_total_count INT NOT NULL,
        matched_total_count INT NOT NULL,
        waiting_for_actual_count INT NOT NULL,
        missing_actual_count INT NOT NULL,
        metric_row_count INT NOT NULL,

        started_at DATETIME2(3) NOT NULL
            CONSTRAINT DF_production_monitoring_runs_started DEFAULT SYSUTCDATETIME(),
        completed_at DATETIME2(3) NOT NULL
            CONSTRAINT DF_production_monitoring_runs_completed DEFAULT SYSUTCDATETIME(),

        CONSTRAINT UQ_production_monitoring_runs_pipeline UNIQUE (pipeline_run_id),

        CONSTRAINT FK_production_monitoring_runs_pipeline
            FOREIGN KEY (pipeline_run_id)
            REFERENCES dbo.pipeline_runs(run_id),

        CONSTRAINT CK_production_monitoring_runs_status CHECK (
            status IN ('NO_OFFICIALS','WAITING_FOR_ACTUAL','PARTIAL','COMPLETED')
        ),

        CONSTRAINT CK_production_monitoring_runs_counts CHECK (
            official_total_count >= 0
            AND matched_total_count >= 0
            AND waiting_for_actual_count >= 0
            AND missing_actual_count >= 0
            AND metric_row_count >= 0
            AND official_total_count = (
                matched_total_count
                + waiting_for_actual_count
                + missing_actual_count
            )
        )
    );

    CREATE INDEX IX_production_monitoring_runs_business_date
        ON dbo.production_monitoring_runs(business_date, completed_at DESC);
END
GO

IF OBJECT_ID('dbo.production_monitoring_metrics', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.production_monitoring_metrics (
        metric_id BIGINT IDENTITY(1,1) NOT NULL
            CONSTRAINT PK_production_monitoring_metrics PRIMARY KEY,

        monitoring_run_id VARCHAR(90) NOT NULL,
        metric_scope VARCHAR(20) NOT NULL,
        horizon INT NOT NULL,
        candidate_id VARCHAR(80) NOT NULL,
        department_id INT NULL,
        sample_count INT NOT NULL,
        through_target_date DATE NOT NULL,

        mae FLOAT NOT NULL,
        rmse FLOAT NOT NULL,
        wape FLOAT NOT NULL,
        r2 FLOAT NULL,
        bias FLOAT NOT NULL,
        p90_abs_error FLOAT NOT NULL,
        max_abs_error FLOAT NOT NULL,
        within_2_rate FLOAT NOT NULL,
        underprediction_rate FLOAT NOT NULL,
        underprediction_mae FLOAT NOT NULL,

        capacity_event_tp INT NOT NULL,
        capacity_event_fp INT NOT NULL,
        capacity_event_fn INT NOT NULL,
        capacity_event_tn INT NOT NULL,
        capacity_event_precision FLOAT NULL,
        capacity_event_recall FLOAT NULL,
        capacity_event_accuracy FLOAT NOT NULL,

        created_at DATETIME2(3) NOT NULL
            CONSTRAINT DF_production_monitoring_metrics_created DEFAULT SYSUTCDATETIME(),

        CONSTRAINT FK_production_monitoring_metrics_run
            FOREIGN KEY (monitoring_run_id)
            REFERENCES dbo.production_monitoring_runs(monitoring_run_id),

        CONSTRAINT FK_production_monitoring_metrics_candidate_horizon
            FOREIGN KEY (candidate_id, horizon)
            REFERENCES dbo.model_candidates(candidate_id, horizon),

        CONSTRAINT FK_production_monitoring_metrics_department
            FOREIGN KEY (department_id)
            REFERENCES dbo.departments(department_id),

        CONSTRAINT CK_production_monitoring_metrics_scope
            CHECK (metric_scope IN ('HORIZON','DEPARTMENT')),

        CONSTRAINT CK_production_monitoring_metrics_scope_department CHECK (
            (metric_scope='HORIZON' AND department_id IS NULL)
            OR
            (metric_scope='DEPARTMENT' AND department_id IS NOT NULL)
        ),

        CONSTRAINT CK_production_monitoring_metrics_horizon
            CHECK (horizon IN (1,3)),

        CONSTRAINT CK_production_monitoring_metrics_values CHECK (
            sample_count > 0
            AND mae >= 0
            AND rmse >= 0
            AND wape >= 0
            AND p90_abs_error >= 0
            AND max_abs_error >= 0
            AND within_2_rate >= 0 AND within_2_rate <= 1
            AND underprediction_rate >= 0 AND underprediction_rate <= 1
            AND underprediction_mae >= 0
            AND capacity_event_tp >= 0
            AND capacity_event_fp >= 0
            AND capacity_event_fn >= 0
            AND capacity_event_tn >= 0
            AND capacity_event_accuracy >= 0 AND capacity_event_accuracy <= 1
            AND (capacity_event_precision IS NULL OR (
                capacity_event_precision >= 0 AND capacity_event_precision <= 1
            ))
            AND (capacity_event_recall IS NULL OR (
                capacity_event_recall >= 0 AND capacity_event_recall <= 1
            ))
        )
    );

    CREATE UNIQUE INDEX UX_production_monitoring_metrics_horizon
        ON dbo.production_monitoring_metrics(
            monitoring_run_id,
            horizon,
            candidate_id
        )
        WHERE metric_scope='HORIZON';

    CREATE UNIQUE INDEX UX_production_monitoring_metrics_department
        ON dbo.production_monitoring_metrics(
            monitoring_run_id,
            horizon,
            candidate_id,
            department_id
        )
        WHERE metric_scope='DEPARTMENT';

    CREATE INDEX IX_production_monitoring_metrics_candidate
        ON dbo.production_monitoring_metrics(candidate_id, horizon, created_at DESC);
END
GO