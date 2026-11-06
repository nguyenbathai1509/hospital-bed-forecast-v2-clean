/* V2-14 - Training lineage extensions.
   Keeps reproducibility metadata at Training Run level.
*/

IF COL_LENGTH('dbo.training_runs', 'code_revision') IS NULL
BEGIN
    ALTER TABLE dbo.training_runs
        ADD code_revision VARCHAR(100) NULL;
END
GO

IF COL_LENGTH('dbo.training_runs', 'random_seed') IS NULL
BEGIN
    ALTER TABLE dbo.training_runs
        ADD random_seed INT NULL;
END
GO

IF COL_LENGTH('dbo.training_runs', 'environment_json') IS NULL
BEGIN
    ALTER TABLE dbo.training_runs
        ADD environment_json NVARCHAR(MAX) NULL;
END
GO

IF COL_LENGTH('dbo.training_runs', 'training_contract_version') IS NULL
BEGIN
    ALTER TABLE dbo.training_runs
        ADD training_contract_version VARCHAR(30) NOT NULL
            CONSTRAINT DF_training_runs_contract_version DEFAULT ('v2.0');
END
GO

IF COL_LENGTH('dbo.training_runs', 'completed_candidate_count') IS NULL
BEGIN
    ALTER TABLE dbo.training_runs
        ADD completed_candidate_count INT NULL;
END
GO

IF NOT EXISTS (
    SELECT 1
    FROM sys.check_constraints
    WHERE name = 'CK_training_runs_random_seed'
)
BEGIN
    ALTER TABLE dbo.training_runs
        ADD CONSTRAINT CK_training_runs_random_seed
            CHECK (random_seed IS NULL OR random_seed >= 0);
END
GO

IF NOT EXISTS (
    SELECT 1
    FROM sys.check_constraints
    WHERE name = 'CK_training_runs_candidate_count'
)
BEGIN
    ALTER TABLE dbo.training_runs
        ADD CONSTRAINT CK_training_runs_candidate_count
            CHECK (
                completed_candidate_count IS NULL
                OR completed_candidate_count >= 0
            );
END
GO