/*
V2 - Migration 010
Promotion quota per business_date + horizon.

Old invariant:
    one NORMAL_PROMOTION / business_date

New invariant:
    one NORMAL_PROMOTION / business_date / horizon

Reason:
H+1 and H+3 are independent Production slots.

The invariant spans:
    dbo.production_changes.business_date
    dbo.production_change_items.horizon

SQL Server cannot create a normal UNIQUE INDEX across two tables,
therefore a database trigger preserves the concurrency/database guard.
*/

CREATE OR ALTER TRIGGER
    dbo.TR_production_change_items_normal_quota_per_horizon
ON dbo.production_change_items
AFTER INSERT, UPDATE
AS
BEGIN
    SET NOCOUNT ON;

    /*
    Only inspect business_date + horizon combinations touched
    by the current statement.

    If more than one committed NORMAL_PROMOTION exists for the
    same business_date + horizon, reject the transaction.
    */
    IF EXISTS
    (
        SELECT 1
        FROM
        (
            SELECT
                pc.business_date,
                pci.horizon,
                COUNT_BIG(*) AS promotion_count
            FROM dbo.production_change_items AS pci
            INNER JOIN dbo.production_changes AS pc
                ON pc.change_id = pci.change_id
            INNER JOIN
            (
                SELECT DISTINCT
                    ipc.business_date,
                    i.horizon
                FROM inserted AS i
                INNER JOIN dbo.production_changes AS ipc
                    ON ipc.change_id = i.change_id
                WHERE
                    ipc.change_kind = 'NORMAL_PROMOTION'
                    AND ipc.status = 'COMMITTED'
            ) AS affected
                ON affected.business_date = pc.business_date
                AND affected.horizon = pci.horizon
            WHERE
                pc.change_kind = 'NORMAL_PROMOTION'
                AND pc.status = 'COMMITTED'
            GROUP BY
                pc.business_date,
                pci.horizon
            HAVING COUNT_BIG(*) > 1
        ) AS duplicate_quota
    )
    BEGIN
        THROW 51020,
            'NORMAL_PROMOTION quota already used for this business_date + horizon.',
            1;
    END;
END
GO


/*
Create the new, narrower database guard first.
Only then remove the old business_date-wide guard.
*/
IF EXISTS
(
    SELECT 1
    FROM sys.indexes
    WHERE
        object_id = OBJECT_ID('dbo.production_changes')
        AND name = 'UX_production_changes_one_normal_per_business_date'
)
BEGIN
    DROP INDEX
        UX_production_changes_one_normal_per_business_date
        ON dbo.production_changes;
END
GO
