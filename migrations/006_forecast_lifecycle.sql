/* V2-17 - Preview / Draft / Official Forecast lifecycle.
   Production prediction creates DRAFT rows. Only explicit confirmation creates
   immutable OFFICIAL rows. The first Official for origin_date+horizon creates
   dbo.daily_model_locks; all remaining departments for that horizon must use
   the same model candidate. Preview is read-only and is not persisted here.
*/

IF OBJECT_ID('dbo.forecast_drafts', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.forecast_drafts (
        draft_id VARCHAR(90) NOT NULL
            CONSTRAINT PK_forecast_drafts PRIMARY KEY,

        origin_date DATE NOT NULL,
        department_id INT NOT NULL,
        horizon INT NOT NULL,
        target_date DATE NOT NULL,

        candidate_id VARCHAR(80) NOT NULL,
        source_mode VARCHAR(20) NOT NULL,
        status VARCHAR(20) NOT NULL,

        prediction_raw FLOAT NOT NULL,
        prediction_rounded INT NOT NULL,
        planned_beds INT NOT NULL,
        predicted_utilization_pct FLOAT NOT NULL,
        capacity_alert BIT NOT NULL,
        capacity_excess_beds INT NOT NULL,

        feature_version VARCHAR(30) NOT NULL,
        data_version VARCHAR(100) NULL,

        created_by NVARCHAR(100) NULL,
        created_at DATETIME2(3) NOT NULL
            CONSTRAINT DF_forecast_drafts_created
            DEFAULT SYSUTCDATETIME(),
        confirmed_at DATETIME2(3) NULL,

        CONSTRAINT FK_forecast_drafts_department
            FOREIGN KEY (department_id)
            REFERENCES dbo.departments(department_id),

        CONSTRAINT FK_forecast_drafts_candidate_horizon
            FOREIGN KEY (candidate_id, horizon)
            REFERENCES dbo.model_candidates(candidate_id, horizon),

        CONSTRAINT CK_forecast_drafts_horizon
            CHECK (horizon IN (1,3)),

        CONSTRAINT CK_forecast_drafts_source_mode
            CHECK (source_mode='PRODUCTION'),

        CONSTRAINT CK_forecast_drafts_status
            CHECK (status IN ('DRAFT','CONFIRMED','VOID')),

        CONSTRAINT CK_forecast_drafts_target_date
            CHECK (target_date=DATEADD(DAY, horizon, origin_date)),

        CONSTRAINT CK_forecast_drafts_values CHECK (
            prediction_rounded >= 0
            AND planned_beds > 0
            AND capacity_excess_beds >= 0
        )
    );

    CREATE UNIQUE INDEX UX_forecast_drafts_one_open
        ON dbo.forecast_drafts(origin_date, department_id, horizon)
        WHERE status='DRAFT';

    CREATE INDEX IX_forecast_drafts_origin_status
        ON dbo.forecast_drafts(origin_date, status, horizon, department_id);
END
GO


IF OBJECT_ID('dbo.official_forecasts', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.official_forecasts (
        official_id VARCHAR(90) NOT NULL
            CONSTRAINT PK_official_forecasts PRIMARY KEY,

        source_draft_id VARCHAR(90) NOT NULL,

        origin_date DATE NOT NULL,
        department_id INT NOT NULL,
        horizon INT NOT NULL,
        target_date DATE NOT NULL,

        candidate_id VARCHAR(80) NOT NULL,

        prediction_raw FLOAT NOT NULL,
        prediction_rounded INT NOT NULL,
        planned_beds INT NOT NULL,
        predicted_utilization_pct FLOAT NOT NULL,
        capacity_alert BIT NOT NULL,
        capacity_excess_beds INT NOT NULL,

        feature_version VARCHAR(30) NOT NULL,
        data_version VARCHAR(100) NULL,

        confirmed_by NVARCHAR(100) NULL,
        issued_at DATETIME2(3) NOT NULL
            CONSTRAINT DF_official_forecasts_issued
            DEFAULT SYSUTCDATETIME(),

        CONSTRAINT UQ_official_forecasts_source_draft
            UNIQUE (source_draft_id),

        CONSTRAINT UQ_official_forecasts_business_key
            UNIQUE (origin_date, department_id, horizon),

        CONSTRAINT FK_official_forecasts_draft
            FOREIGN KEY (source_draft_id)
            REFERENCES dbo.forecast_drafts(draft_id),

        CONSTRAINT FK_official_forecasts_department
            FOREIGN KEY (department_id)
            REFERENCES dbo.departments(department_id),

        CONSTRAINT FK_official_forecasts_candidate_horizon
            FOREIGN KEY (candidate_id, horizon)
            REFERENCES dbo.model_candidates(candidate_id, horizon),

        CONSTRAINT CK_official_forecasts_horizon
            CHECK (horizon IN (1,3)),

        CONSTRAINT CK_official_forecasts_target_date
            CHECK (target_date=DATEADD(DAY, horizon, origin_date)),

        CONSTRAINT CK_official_forecasts_values CHECK (
            prediction_rounded >= 0
            AND planned_beds > 0
            AND capacity_excess_beds >= 0
        )
    );

    CREATE INDEX IX_official_forecasts_target
        ON dbo.official_forecasts(target_date, department_id, horizon);

    CREATE INDEX IX_official_forecasts_candidate
        ON dbo.official_forecasts(candidate_id, origin_date);
END
GO