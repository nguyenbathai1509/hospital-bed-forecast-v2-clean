/* V2-11 Phase 1 - SQL Foundation
   SQL Server, schema dbo. Idempotency is enforced by PK/UQ constraints.
   This migration intentionally contains only the Phase-1 data foundation tables.
*/

IF OBJECT_ID('dbo.departments', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.departments (
        department_id INT NOT NULL CONSTRAINT PK_departments PRIMARY KEY,
        department_code NVARCHAR(30) NOT NULL,
        department_name NVARCHAR(200) NOT NULL,
        planned_beds INT NOT NULL,
        is_active BIT NOT NULL CONSTRAINT DF_departments_is_active DEFAULT (1),
        created_at DATETIME2(3) NOT NULL CONSTRAINT DF_departments_created_at DEFAULT SYSUTCDATETIME(),
        updated_at DATETIME2(3) NULL,
        CONSTRAINT UQ_departments_code UNIQUE (department_code),
        CONSTRAINT CK_departments_planned_beds CHECK (planned_beds > 0)
    );
END
GO

IF OBJECT_ID('dbo.pipeline_runs', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.pipeline_runs (
        run_id VARCHAR(60) NOT NULL CONSTRAINT PK_pipeline_runs PRIMARY KEY,
        business_date DATE NULL,
        source_mode VARCHAR(30) NOT NULL,
        source_ref NVARCHAR(1000) NULL,
        data_version VARCHAR(100) NULL,
        status VARCHAR(30) NOT NULL,
        started_at DATETIME2(3) NOT NULL,
        completed_at DATETIME2(3) NULL,
        rows_extracted INT NULL,
        quality_error_count INT NOT NULL CONSTRAINT DF_pipeline_error DEFAULT (0),
        quality_warning_count INT NOT NULL CONSTRAINT DF_pipeline_warning DEFAULT (0),
        quality_check_count INT NOT NULL CONSTRAINT DF_pipeline_check DEFAULT (0),
        error_message NVARCHAR(MAX) NULL,
        CONSTRAINT CK_pipeline_status CHECK (status IN ('RUNNING','FAILED','BOOTSTRAP_COMPLETED','WAITING','COMPLETED','DATA_READY')),
        CONSTRAINT CK_pipeline_quality_counts CHECK (quality_error_count >= 0 AND quality_warning_count >= 0 AND quality_check_count >= 0)
    );
    CREATE INDEX IX_pipeline_runs_status_date ON dbo.pipeline_runs(status, business_date);
END
GO

IF OBJECT_ID('dbo.raw_bed_daily', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.raw_bed_daily (
        raw_id BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_raw_bed_daily PRIMARY KEY,
        business_date DATE NOT NULL,
        source_weekday NVARCHAR(10) NULL,
        source_month INT NULL,
        department_id INT NOT NULL,
        department_code NVARCHAR(30) NOT NULL,
        department_name NVARCHAR(200) NOT NULL,
        planned_beds INT NOT NULL,
        occupied_start INT NOT NULL,
        admissions INT NOT NULL,
        transfer_in INT NOT NULL,
        discharges INT NOT NULL,
        transfer_out INT NOT NULL,
        occupied_end INT NOT NULL,
        occupied_beds INT NOT NULL,
        balance_status NVARCHAR(30) NULL,
        occupancy_rate DECIMAL(12,6) NULL,
        source_file NVARCHAR(260) NULL,
        source_row_num INT NULL,
        source_updated_at DATETIME2(3) NULL,
        source_hash CHAR(64) NOT NULL,
        revision_no INT NOT NULL CONSTRAINT DF_raw_revision DEFAULT (1),
        ingested_at DATETIME2(3) NOT NULL CONSTRAINT DF_raw_ingested DEFAULT SYSUTCDATETIME(),
        pipeline_run_id VARCHAR(60) NOT NULL,
        CONSTRAINT UQ_raw_business_key UNIQUE (business_date, department_id),
        CONSTRAINT FK_raw_department FOREIGN KEY (department_id) REFERENCES dbo.departments(department_id),
        CONSTRAINT FK_raw_pipeline_run FOREIGN KEY (pipeline_run_id) REFERENCES dbo.pipeline_runs(run_id),
        CONSTRAINT CK_raw_planned_beds CHECK (planned_beds > 0),
        CONSTRAINT CK_raw_counts_nonnegative CHECK (
            occupied_start >= 0 AND admissions >= 0 AND transfer_in >= 0 AND discharges >= 0 AND
            transfer_out >= 0 AND occupied_end >= 0 AND occupied_beds >= 0
        ),
        CONSTRAINT CK_raw_revision CHECK (revision_no >= 1)
    );
    CREATE INDEX IX_raw_department_date ON dbo.raw_bed_daily(department_id, business_date);
END
GO

IF OBJECT_ID('dbo.data_quality_issues', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.data_quality_issues (
        issue_id BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_data_quality_issues PRIMARY KEY,
        pipeline_run_id VARCHAR(60) NOT NULL,
        business_date DATE NULL,
        department_id INT NULL,
        rule_id VARCHAR(10) NOT NULL,
        severity VARCHAR(10) NOT NULL,
        field_name NVARCHAR(100) NULL,
        expected_value NVARCHAR(500) NULL,
        actual_value NVARCHAR(500) NULL,
        difference_value FLOAT NULL,
        message NVARCHAR(1000) NOT NULL,
        detected_at DATETIME2(3) NOT NULL CONSTRAINT DF_dq_detected DEFAULT SYSUTCDATETIME(),
        is_resolved BIT NOT NULL CONSTRAINT DF_dq_resolved DEFAULT (0),
        resolved_at DATETIME2(3) NULL,
        resolved_by NVARCHAR(100) NULL,
        CONSTRAINT FK_dq_pipeline_run FOREIGN KEY (pipeline_run_id) REFERENCES dbo.pipeline_runs(run_id),
        CONSTRAINT FK_dq_department FOREIGN KEY (department_id) REFERENCES dbo.departments(department_id),
        CONSTRAINT CK_dq_rule CHECK (rule_id IN ('DQ01','DQ02','DQ03','DQ04','DQ05','DQ06','DQ07','DQ08','DQ09','DQ10','DQ11','DQ12')),
        CONSTRAINT CK_dq_severity CHECK (severity IN ('ERROR','WARNING','CHECK'))
    );
    CREATE INDEX IX_dq_run_severity ON dbo.data_quality_issues(pipeline_run_id, severity);
    CREATE INDEX IX_dq_department_date ON dbo.data_quality_issues(department_id, business_date);
END
GO

IF OBJECT_ID('dbo.clean_bed_daily', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.clean_bed_daily (
        clean_id BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_clean_bed_daily PRIMARY KEY,
        business_date DATE NOT NULL,
        department_id INT NOT NULL,
        department_code NVARCHAR(30) NOT NULL,
        department_name NVARCHAR(200) NOT NULL,
        planned_beds INT NOT NULL,
        occupied_start INT NOT NULL,
        admissions INT NOT NULL,
        transfer_in INT NOT NULL,
        discharges INT NOT NULL,
        transfer_out INT NOT NULL,
        occupied_end INT NOT NULL,
        occupied_beds INT NOT NULL,
        balance_status NVARCHAR(30) NULL,
        expected_occupied_end INT NOT NULL,
        balance_error INT NOT NULL,
        quality_flag VARCHAR(10) NOT NULL,
        occupied_consistency_error INT NOT NULL,
        source_revision_no INT NOT NULL,
        pipeline_run_id VARCHAR(60) NOT NULL,
        built_at DATETIME2(3) NOT NULL CONSTRAINT DF_clean_built DEFAULT SYSUTCDATETIME(),
        CONSTRAINT UQ_clean_business_key UNIQUE (business_date, department_id),
        CONSTRAINT FK_clean_department FOREIGN KEY (department_id) REFERENCES dbo.departments(department_id),
        CONSTRAINT FK_clean_pipeline_run FOREIGN KEY (pipeline_run_id) REFERENCES dbo.pipeline_runs(run_id),
        CONSTRAINT CK_clean_quality_flag CHECK (quality_flag IN ('PASS','WARNING','CHECK')),
        CONSTRAINT CK_clean_planned_beds CHECK (planned_beds > 0)
    );
    CREATE INDEX IX_clean_department_date ON dbo.clean_bed_daily(department_id, business_date);
END
GO

IF OBJECT_ID('dbo.bed_features_daily', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.bed_features_daily (
        feature_id BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_bed_features_daily PRIMARY KEY,
        origin_date DATE NOT NULL,
        department_id INT NOT NULL,
        feature_version VARCHAR(30) NOT NULL,
        planned_beds INT NOT NULL,
        occupied_beds INT NOT NULL,
        admissions INT NOT NULL,
        discharges INT NOT NULL,
        transfer_in INT NOT NULL,
        transfer_out INT NOT NULL,
        net_flow INT NOT NULL,
        occupied_beds_lag_1 INT NULL,
        occupied_beds_lag_2 INT NULL,
        occupied_beds_lag_3 INT NULL,
        occupied_beds_mean_3 FLOAT NULL,
        occupied_beds_std_3 FLOAT NULL,
        admissions_lag_1 INT NULL,
        admissions_lag_2 INT NULL,
        admissions_lag_3 INT NULL,
        admissions_mean_3 FLOAT NULL,
        discharges_lag_1 INT NULL,
        discharges_lag_2 INT NULL,
        discharges_lag_3 INT NULL,
        discharges_mean_3 FLOAT NULL,
        net_flow_lag_1 INT NULL,
        net_flow_lag_2 INT NULL,
        net_flow_lag_3 INT NULL,
        net_flow_mean_3 FLOAT NULL,
        is_weekend BIT NOT NULL,
        dow_sin FLOAT NOT NULL,
        dow_cos FLOAT NOT NULL,
        source_revision_no INT NOT NULL,
        built_at DATETIME2(3) NOT NULL CONSTRAINT DF_feature_built DEFAULT SYSUTCDATETIME(),
        CONSTRAINT UQ_feature_business_key UNIQUE (origin_date, department_id, feature_version),
        CONSTRAINT FK_feature_department FOREIGN KEY (department_id) REFERENCES dbo.departments(department_id)
    );
    CREATE INDEX IX_feature_department_date ON dbo.bed_features_daily(department_id, origin_date);
END
GO

IF OBJECT_ID('dbo.ml_samples', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.ml_samples (
        sample_id BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_ml_samples PRIMARY KEY,
        origin_date DATE NOT NULL,
        department_id INT NOT NULL,
        horizon INT NOT NULL,
        target_date DATE NOT NULL,
        target_occupied_beds INT NOT NULL,
        feature_version VARCHAR(30) NOT NULL,
        data_version VARCHAR(100) NULL,
        matured_at DATETIME2(3) NOT NULL CONSTRAINT DF_ml_matured DEFAULT SYSUTCDATETIME(),
        CONSTRAINT UQ_ml_sample UNIQUE (origin_date, department_id, horizon, feature_version),
        CONSTRAINT FK_ml_department FOREIGN KEY (department_id) REFERENCES dbo.departments(department_id),
        CONSTRAINT CK_ml_horizon CHECK (horizon IN (1,3)),
        CONSTRAINT CK_ml_target_nonnegative CHECK (target_occupied_beds >= 0)
    );
    CREATE INDEX IX_ml_target_department_horizon ON dbo.ml_samples(target_date, department_id, horizon);
END
GO
