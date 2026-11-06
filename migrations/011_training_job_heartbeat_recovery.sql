/* V2 - Training Job heartbeat foundation.

   Adds an internal heartbeat timestamp for asynchronous API Training Jobs.

   This column is orchestration metadata only:
   - does not change the public FastAPI contract;
   - does not change dbo.training_runs scientific semantics;
   - does not change Recommendation / Promotion / Forecast lifecycle.

   The migration is additive and idempotent for an existing V2 database.
*/

IF OBJECT_ID('dbo.api_training_jobs', 'U') IS NOT NULL
   AND COL_LENGTH('dbo.api_training_jobs', 'heartbeat_at') IS NULL
BEGIN
    ALTER TABLE dbo.api_training_jobs
        ADD heartbeat_at DATETIME2(3) NULL;
END
GO
