/*
V2 - Migration 010
Promotion quota per business_date + horizon.

Old invariant:
    one NORMAL_PROMOTION / business_date

New invariant:
    one NORMAL_PROMOTION / business_date / horizon

H+1 and H+3 are independent Production slots.

The invariant spans:
    dbo.production_changes.business_date
    dbo.production_change_items.horizon

A trigger plus transaction-scoped SQL Server application lock is used
because a normal UNIQUE INDEX cannot span the two tables.
*/

CREATE OR ALTER TRIGGER
    dbo.TR_production_change_items_normal_quota_per_horizon
ON dbo.production_change_items
AFTER INSERT, UPDATE
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE
        @business_date DATE,
        @horizon INT,
        @resource NVARCHAR(255),
        @lock_result INT;

    /*
    Lock affected business_date+horizon keys in deterministic order.

    sp_getapplock with LockOwner='Transaction' means:
    - concurrent requests for the SAME date+horizon are serialized;
    - H+1 and H+3 remain independent quota keys;
    - lock is released automatically with COMMIT/ROLLBACK.
    */
    DECLARE quota_cursor CURSOR LOCAL FAST_FORWARD FOR
        SELECT DISTINCT
            pc.business_date,
            i.horizon
        FROM inserted AS i
        INNER JOIN dbo.production_changes AS pc
            ON pc.change_id = i.change_id
        WHERE
            pc.change_kind = 'NORMAL_PROMOTION'
            AND pc.status = 'COMMITTED'
        ORDER BY
            pc.business_date,
            i.horizon;

    OPEN quota_cursor;

    FETCH NEXT FROM quota_cursor
        INTO @business_date, @horizon;

    WHILE @@FETCH_STATUS = 0
    BEGIN
        SET @resource =
            CONCAT(
                'HBV2:NORMAL_PROMOTION:',
                CONVERT(CHAR(10), @business_date, 23),
                ':H',
                CONVERT(VARCHAR(10), @horizon)
            );

        EXEC @lock_result = sys.sp_getapplock
            @Resource = @resource,
            @LockMode = 'Exclusive',
            @LockOwner = 'Transaction',
            @LockTimeout = 10000;

        IF @lock_result < 0
        BEGIN
            CLOSE quota_cursor;
            DEALLOCATE quota_cursor;

            THROW 51021,
                'Could not acquire NORMAL_PROMOTION quota lock.',
                1;
        END;

        /*
        The lock has now serialized this business_date+horizon key.
        Reject if another committed NORMAL_PROMOTION already owns it.
        */
        IF
        (
            SELECT COUNT_BIG(*)
            FROM dbo.production_change_items AS pci
                WITH (READPAST)
            INNER JOIN dbo.production_changes AS pc
                WITH (READPAST)
                ON pc.change_id = pci.change_id
            WHERE
                pc.business_date = @business_date
                AND pci.horizon = @horizon
                AND pc.change_kind = 'NORMAL_PROMOTION'
                AND pc.status = 'COMMITTED'
        ) > 1
        BEGIN
            CLOSE quota_cursor;
            DEALLOCATE quota_cursor;

            THROW 51020,
                'NORMAL_PROMOTION quota already used for this business_date + horizon.',
                1;
        END;

        FETCH NEXT FROM quota_cursor
            INTO @business_date, @horizon;
    END;

    CLOSE quota_cursor;
    DEALLOCATE quota_cursor;
END
GO


/*
production_changes is audit history.
Do not allow quota-defining header fields to change after creation.
*/
CREATE OR ALTER TRIGGER
    dbo.TR_production_changes_quota_fields_immutable
ON dbo.production_changes
AFTER UPDATE
AS
BEGIN
    SET NOCOUNT ON;

    IF
        UPDATE(business_date)
        OR UPDATE(change_kind)
        OR UPDATE(status)
    BEGIN
        THROW 51022,
            'business_date, change_kind and status are immutable for production_changes.',
            1;
    END;
END
GO


/*
The new per-horizon database guard is installed first.
Only then remove the old business-date-wide unique index.
*/
IF EXISTS
(
    SELECT 1
    FROM sys.indexes
    WHERE
        object_id = OBJECT_ID('dbo.production_changes')
        AND name =
            'UX_production_changes_one_normal_per_business_date'
)
BEGIN
    DROP INDEX
        UX_production_changes_one_normal_per_business_date
        ON dbo.production_changes;
END
GO
