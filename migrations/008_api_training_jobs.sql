/* V2-19 Part C1 - Persistent FastAPI Training Jobs.
   A Training Job is the asynchronous HTTP-facing wrapper around the already verified
   V2-14 Training Service + V2-15 Recommendation Engine.

   This table does NOT replace dbo.training_runs.  dbo.training_runs remains the
   scientific/audit Training Run.  api_training_jobs only tracks API orchestration so
   POST /training/start can return immediately and clients can poll status safely.
*/

IF OBJECT_ID('dbo.api_training_jobs', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.api_training_jobs (
        job_id VARCHAR(80) NOT NULL
            CONSTRAINT PK_api_training_jobs PRIMARY KEY,

        business_date DATE NOT NULL,
        source_pipeline_run_id VARCHAR(60) NOT NULL,
        status VARCHAR(20) NOT NULL,
        requested_by NVARCHAR(100) NOT NULL,
        random_seed INT NOT NULL,

        training_run_id VARCHAR(60) NULL,
        result_json NVARCHAR(MAX) NULL,
        error_message NVARCHAR(MAX) NULL,

        created_at DATETIME2(3) NOT NULL
            CONSTRAINT DF_api_training_jobs_created DEFAULT SYSUTCDATETIME(),
        started_at DATETIME2(3) NULL,
        completed_at DATETIME2(3) NULL,

        CONSTRAINT FK_api_training_jobs_pipeline_run
            FOREIGN KEY (source_pipeline_run_id)
            REFERENCES dbo.pipeline_runs(run_id),

        CONSTRAINT FK_api_training_jobs_training_run
            FOREIGN KEY (training_run_id)
            REFERENCES dbo.training_runs(run_id),

        CONSTRAINT CK_api_training_jobs_status CHECK (
            status IN ('PENDING','RUNNING','COMPLETED','FAILED')
        ),

        CONSTRAINT CK_api_training_jobs_random_seed CHECK (
            random_seed >= 0
        ),

        CONSTRAINT CK_api_training_jobs_timestamps CHECK (
            (started_at IS NULL OR started_at >= created_at)
            AND
            (completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at)
        )
    );

    CREATE INDEX IX_api_training_jobs_business_status
        ON dbo.api_training_jobs(business_date, status, created_at DESC);

    CREATE INDEX IX_api_training_jobs_training_run
        ON dbo.api_training_jobs(training_run_id, created_at DESC);
END
GO