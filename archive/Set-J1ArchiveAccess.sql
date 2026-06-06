-- ============================================================
-- J1 EX Retirement: Read-Only Archive Database Setup
-- Target: Methodist University
-- ============================================================
--
-- PREREQUISITES — run these steps BEFORE executing this script:
--
--   1. While J1 is still running, take a full SQL Server backup:
--        BACKUP DATABASE [CX_LIVE]
--            TO DISK = N'D:\Backups\CX_LIVE_PreRetirement_YYYYMMDD.bak'
--            WITH COMPRESSION, CHECKSUM, STATS = 5;
--
--   2. Restore the backup as a new database on your archive server
--      (same server is fine; use a distinct name):
--        RESTORE DATABASE [J1_Archive]
--            FROM DISK = N'D:\Backups\CX_LIVE_PreRetirement_YYYYMMDD.bak'
--            WITH MOVE 'CX_LIVE'     TO N'D:\Data\J1_Archive.mdf',
--                 MOVE 'CX_LIVE_log' TO N'D:\Logs\J1_Archive_log.ldf',
--                 RECOVERY, STATS = 5;
--      Adjust logical file names from the backup's RESTORE FILELISTONLY output.
--
--   3. Verify the restore, then run this script against [J1_Archive].
--
-- ============================================================

USE [J1_Archive];   -- Change if you named the restore differently
GO

-- ── 1. Lock the archive database as read-only ──────────────────────────────
-- ROLLBACK IMMEDIATE terminates any open connections on J1_Archive instantly.
-- After this, no INSERT / UPDATE / DELETE / DDL is possible. SELECTs still work.
ALTER DATABASE [J1_Archive] SET READ_ONLY WITH ROLLBACK IMMEDIATE;
GO

-- ── 2a. SQL Server login (if not using Windows/AD authentication) ───────────
-- Replace the password with one that meets your institution's password policy.
-- Omit this block and use 2b instead if your users authenticate via Active Directory.
IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = N'j1_archive_reader')
BEGIN
    CREATE LOGIN [j1_archive_reader]
        WITH PASSWORD            = N'<ReplaceWithSecurePassword!>',
             DEFAULT_DATABASE    = [J1_Archive],
             CHECK_EXPIRATION    = OFF,
             CHECK_POLICY        = ON;
END
GO

CREATE USER [j1_archive_reader] FOR LOGIN [j1_archive_reader];
GO

ALTER ROLE [db_datareader] ADD MEMBER [j1_archive_reader];
GO

GRANT VIEW DEFINITION TO [j1_archive_reader];
GO

-- ── 2b. Windows / Active Directory group login (alternative to 2a) ──────────
-- Uncomment and adjust the domain\group name if you prefer AD authentication.
-- Create an AD security group (e.g., "MU-J1-Archive-Readers") and add staff to it.
--
-- IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = N'METHODIST\MU-J1-Archive-Readers')
-- BEGIN
--     CREATE LOGIN [METHODIST\MU-J1-Archive-Readers] FROM WINDOWS;
-- END
-- GO
-- CREATE USER [METHODIST\MU-J1-Archive-Readers]
--     FOR LOGIN [METHODIST\MU-J1-Archive-Readers];
-- GO
-- ALTER ROLE [db_datareader] ADD MEMBER [METHODIST\MU-J1-Archive-Readers];
-- GO
-- GRANT VIEW DEFINITION TO [METHODIST\MU-J1-Archive-Readers];
-- GO

-- ── 3. Verify ───────────────────────────────────────────────────────────────
-- Expected: is_read_only = 1
SELECT name, is_read_only, state_desc
FROM   sys.databases
WHERE  name = N'J1_Archive';

-- Expected: role_principal_name = 'db_datareader'
SELECT dp.name             AS member,
       rp.name             AS role_principal_name
FROM   sys.database_role_members drm
JOIN   sys.database_principals   dp ON dp.principal_id = drm.member_principal_id
JOIN   sys.database_principals   rp ON rp.principal_id = drm.role_principal_id
WHERE  dp.name IN (N'j1_archive_reader', N'METHODIST\MU-J1-Archive-Readers');

-- ── 4. Connection string for staff / reporting tools ───────────────────────
-- SQL Server login:
--   Server=<archive-server>;Database=J1_Archive;User Id=j1_archive_reader;Password=<pw>;
-- Windows auth (AD group — user must be in the AD group):
--   Server=<archive-server>;Database=J1_Archive;Integrated Security=true;
--
-- Staff can connect with any SQL client: SSMS, Azure Data Studio, DBeaver, Excel, etc.
-- The READ_ONLY flag is enforced by SQL Server; no application-layer controls needed.
