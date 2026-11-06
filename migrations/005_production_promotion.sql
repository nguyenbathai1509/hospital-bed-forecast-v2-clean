/* V2-16 - Production Promotion + Rollback governance.
   Adds audited Production Change Transactions, per-horizon change items,
   and the daily model lock contract needed to decide IMMEDIATE vs NEXT_CYCLE.
   This migration does NOT create Official Forecasts; V2-17 will write locks
   only when the first Official Forecast for an origin_date+horizon is confirmed.
*/

IF OBJECT_ID('dbo.production_changes', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.production_changes (
        change_id VARCHAR(90) NOT NULL
            CONSTRAINT PK_production_changes PRIMARY KEY,

        business_date DATE NOT NULL,
        change_kind VARCHAR(30) NOT NULL,
        status VARCHAR(20) NOT NULL,

        requested_by NVARCHAR(100) NULL,
        change_reason NVARCHAR(1000) NOT NULL,
        confirmation_mode VARCHAR(30) NOT NULL,

        created_at DATETIME2(3) NOT NULL
            CONSTRAINT DF_production_changes_created
            DEFAULT SYSUTCDATETIME(),

        confirmed_at DATETIME2(3) NOT NULL
            CONSTRAINT DF_production_changes_confirmed
            DEFAULT SYSUTCDATETIME(),

        CONSTRAINT CK_production_changes_kind CHECK (
            change_kind IN (
                'NORMAL_PROMOTION',
                'EMERGENCY_ROLLBACK'
            )
        ),

        CONSTRAINT CK_production_changes_status CHECK (
            status IN ('COMMITTED')
        ),

        CONSTRAINT CK_production_changes_confirmation CHECK (
            confirmation_mode IN ('EXPLICIT_TEXT')
        )
    );

    CREATE INDEX IX_production_changes_business_date
        ON dbo.production_changes(business_date, created_at DESC);

    CREATE UNIQUE INDEX UX_production_changes_one_normal_per_business_date
        ON dbo.production_changes(business_date)
        WHERE change_kind='NORMAL_PROMOTION' AND status='COMMITTED';
END
GO


IF OBJECT_ID('dbo.production_change_items', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.production_change_items (
        change_id VARCHAR(90) NOT NULL,
        horizon INT NOT NULL,

        from_candidate_id VARCHAR(80) NULL,
        to_candidate_id VARCHAR(80) NOT NULL,

        effect VARCHAR(20) NOT NULL,
        effective_from_business_date DATE NOT NULL,
        daily_lock_present BIT NOT NULL,

        applied_at DATETIME2(3) NULL,

        CONSTRAINT PK_production_change_items
            PRIMARY KEY (change_id, horizon),

        CONSTRAINT FK_production_change_items_change
            FOREIGN KEY (change_id)
            REFERENCES dbo.production_changes(change_id),

        CONSTRAINT FK_production_change_items_from_candidate
            FOREIGN KEY (from_candidate_id, horizon)
            REFERENCES dbo.model_candidates(candidate_id, horizon),

        CONSTRAINT FK_production_change_items_to_candidate
            FOREIGN KEY (to_candidate_id, horizon)
            REFERENCES dbo.model_candidates(candidate_id, horizon),

        CONSTRAINT CK_production_change_items_horizon
            CHECK (horizon IN (1,3)),

        CONSTRAINT CK_production_change_items_effect
            CHECK (effect IN ('IMMEDIATE','NEXT_CYCLE'))
    );

    CREATE INDEX IX_production_change_items_effective
        ON dbo.production_change_items(
            effective_from_business_date,
            effect,
            horizon
        );
END
GO


IF OBJECT_ID('dbo.daily_model_locks', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.daily_model_locks (
        origin_date DATE NOT NULL,
        horizon INT NOT NULL,
        model_candidate_id VARCHAR(80) NOT NULL,
        locked_at DATETIME2(3) NOT NULL
            CONSTRAINT DF_daily_model_locks_locked
            DEFAULT SYSUTCDATETIME(),
        trigger_department_id INT NOT NULL,

        CONSTRAINT PK_daily_model_locks
            PRIMARY KEY (origin_date, horizon),

        CONSTRAINT FK_daily_model_locks_candidate
            FOREIGN KEY (model_candidate_id, horizon)
            REFERENCES dbo.model_candidates(candidate_id, horizon),

        CONSTRAINT FK_daily_model_locks_department
            FOREIGN KEY (trigger_department_id)
            REFERENCES dbo.departments(department_id),

        CONSTRAINT CK_daily_model_locks_horizon
            CHECK (horizon IN (1,3))
    );

    CREATE INDEX IX_daily_model_locks_candidate
        ON dbo.daily_model_locks(model_candidate_id, origin_date);
END
GO