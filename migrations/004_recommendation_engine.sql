/* V2-15 - Dynamic Recommendation Engine + immutable recommendation history.
   Recommendation is advisory only. This migration does NOT promote Production.
*/

IF OBJECT_ID('dbo.model_recommendations', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.model_recommendations (
        recommendation_id VARCHAR(90) NOT NULL
            CONSTRAINT PK_model_recommendations PRIMARY KEY,

        run_id VARCHAR(60) NOT NULL,
        horizon INT NOT NULL,

        best_candidate_id VARCHAR(80) NOT NULL,
        champion_candidate_id VARCHAR(80) NOT NULL,
        recommended_candidate_id VARCHAR(80) NOT NULL,

        champion_source VARCHAR(30) NOT NULL,
        action VARCHAR(20) NOT NULL,

        improvement_pct FLOAT NOT NULL,
        minimum_improvement_pct FLOAT NOT NULL,
        guardrail_pass BIT NOT NULL,

        reason_code VARCHAR(80) NOT NULL,
        reason_json NVARCHAR(MAX) NOT NULL,
        guardrail_json NVARCHAR(MAX) NOT NULL,
        policy_json NVARCHAR(MAX) NOT NULL,

        created_at DATETIME2(3) NOT NULL
            CONSTRAINT DF_model_recommendations_created
            DEFAULT SYSUTCDATETIME(),

        CONSTRAINT FK_model_recommendations_run
            FOREIGN KEY (run_id)
            REFERENCES dbo.training_runs(run_id),

        CONSTRAINT FK_model_recommendations_best
            FOREIGN KEY (best_candidate_id, horizon)
            REFERENCES dbo.model_candidates(candidate_id, horizon),

        CONSTRAINT FK_model_recommendations_champion
            FOREIGN KEY (champion_candidate_id, horizon)
            REFERENCES dbo.model_candidates(candidate_id, horizon),

        CONSTRAINT FK_model_recommendations_recommended
            FOREIGN KEY (recommended_candidate_id, horizon)
            REFERENCES dbo.model_candidates(candidate_id, horizon),

        CONSTRAINT CK_model_recommendations_horizon
            CHECK (horizon IN (1,3)),

        CONSTRAINT CK_model_recommendations_champion_source
            CHECK (
                champion_source IN (
                    'PRODUCTION',
                    'BOOTSTRAP_REFERENCE'
                )
            ),

        CONSTRAINT CK_model_recommendations_action
            CHECK (action IN ('PROMOTE','KEEP')),

        CONSTRAINT CK_model_recommendations_improvement_threshold
            CHECK (minimum_improvement_pct >= 0),

        CONSTRAINT UQ_model_recommendations_run_horizon
            UNIQUE (run_id, horizon)
    );

    CREATE INDEX IX_model_recommendations_horizon_created
        ON dbo.model_recommendations(horizon, created_at DESC);
END
GO

IF OBJECT_ID('dbo.model_candidate_rankings', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.model_candidate_rankings (
        recommendation_id VARCHAR(90) NOT NULL,
        candidate_id VARCHAR(80) NOT NULL,
        horizon INT NOT NULL,
        rank_no INT NOT NULL,
        is_best_candidate BIT NOT NULL,

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
            CONSTRAINT DF_model_candidate_rankings_created
            DEFAULT SYSUTCDATETIME(),

        CONSTRAINT PK_model_candidate_rankings
            PRIMARY KEY (recommendation_id, candidate_id),

        CONSTRAINT FK_model_candidate_rankings_recommendation
            FOREIGN KEY (recommendation_id)
            REFERENCES dbo.model_recommendations(recommendation_id),

        CONSTRAINT FK_model_candidate_rankings_candidate
            FOREIGN KEY (candidate_id, horizon)
            REFERENCES dbo.model_candidates(candidate_id, horizon),

        CONSTRAINT CK_model_candidate_rankings_horizon
            CHECK (horizon IN (1,3)),

        CONSTRAINT CK_model_candidate_rankings_rank
            CHECK (rank_no >= 1),

        CONSTRAINT UQ_model_candidate_rankings_rank
            UNIQUE (recommendation_id, rank_no)
    );

    CREATE INDEX IX_model_candidate_rankings_horizon_rank
        ON dbo.model_candidate_rankings(horizon, rank_no);
END
GO