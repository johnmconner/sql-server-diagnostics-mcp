/*
Provision a SQL-authenticated read-only login for SQL TShooter.

Update these values before running:
  - @LoginName
  - @LoginPassword
  - @TargetDatabase
  - @GrantSqlAgentReadRole if you want get_failed_jobs to work on non-Express editions
*/

DECLARE @LoginName sysname = N'sql_tshooter_ro';
DECLARE @LoginPassword nvarchar(256) = N'UseA_StrongPassword!123';
DECLARE @TargetDatabase sysname = N'test-db';
DECLARE @GrantSqlAgentReadRole bit = 1;

DECLARE @MajorVersion int = CONVERT(int, SERVERPROPERTY('ProductMajorVersion'));
DECLARE @ServerPermission sysname =
    CASE
        WHEN @MajorVersion >= 16 THEN N'VIEW SERVER PERFORMANCE STATE'
        ELSE N'VIEW SERVER STATE'
    END;

IF DB_ID(@TargetDatabase) IS NULL
BEGIN
    THROW 50000, 'Target database does not exist.', 1;
END;

IF SUSER_ID(@LoginName) IS NULL
BEGIN
    DECLARE @CreateLoginSql nvarchar(max) =
        N'CREATE LOGIN ' + QUOTENAME(@LoginName)
        + N' WITH PASSWORD = ' + QUOTENAME(@LoginPassword, '''')
        + N', CHECK_POLICY = ON, CHECK_EXPIRATION = ON;';
    EXEC(@CreateLoginSql);
END;

DECLARE @CreateUserSql nvarchar(max) =
    N'USE ' + QUOTENAME(@TargetDatabase) + N';
      IF USER_ID(' + QUOTENAME(@LoginName, '''') + N') IS NULL
      BEGIN
          CREATE USER ' + QUOTENAME(@LoginName) + N' FOR LOGIN ' + QUOTENAME(@LoginName) + N';
      END;';
EXEC(@CreateUserSql);

DECLARE @GrantServerPermissionSql nvarchar(max) =
    N'USE [master];
      IF NOT EXISTS (
          SELECT 1
          FROM sys.server_permissions p
          INNER JOIN sys.server_principals sp
              ON p.grantee_principal_id = sp.principal_id
          WHERE sp.name = ' + QUOTENAME(@LoginName, '''') + N'
            AND p.permission_name = ' + QUOTENAME(@ServerPermission, '''') + N'
      )
      BEGIN
          GRANT ' + QUOTENAME(@ServerPermission) + N' TO ' + QUOTENAME(@LoginName) + N';
      END;';
EXEC(@GrantServerPermissionSql);

IF @GrantSqlAgentReadRole = 1
AND EXISTS (
    SELECT 1
    FROM sys.databases
    WHERE name = N'msdb'
)
BEGIN
    DECLARE @GrantMsdbSql nvarchar(max) =
        N'USE [msdb];
          IF EXISTS (
              SELECT 1
              FROM sys.database_principals
              WHERE name = N''SQLAgentReaderRole''
          )
          AND NOT EXISTS (
              SELECT 1
              FROM sys.database_role_members drm
              INNER JOIN sys.database_principals role_principal
                  ON drm.role_principal_id = role_principal.principal_id
              INNER JOIN sys.database_principals member_principal
                  ON drm.member_principal_id = member_principal.principal_id
              WHERE role_principal.name = N''SQLAgentReaderRole''
                AND member_principal.name = ' + QUOTENAME(@LoginName, '''') + N'
          )
          BEGIN
              ALTER ROLE [SQLAgentReaderRole] ADD MEMBER ' + QUOTENAME(@LoginName) + N';
          END;';
    EXEC(@GrantMsdbSql);
END;

SELECT
    @LoginName AS login_name,
    @TargetDatabase AS target_database,
    @ServerPermission AS granted_server_permission,
    @GrantSqlAgentReadRole AS sql_agent_role_requested;

