/* Pool (MatchedId side), one batch. Only id + native name: the full rows are
   fetched later for the matched ids only (get_pool_by_ids.sql).

   Parameters, in order (pyodbc "?"):
     1. batch size
     2. last id of the previous batch ('' for the first batch)

   KEEP  "c.id > CAST(? AS VARCHAR(100))"  and  "ORDER BY c.id"  - without both
   the loop never advances. The CAST keeps the parameter VARCHAR so SQL Server
   can seek the id index instead of converting every row. */
SELECT TOP (?)
    c.id                                        AS id,
    CAST(c.nativename AS VARBINARY(MAX))        AS native_name
FROM bvdaffils.dbo.companies c WITH (NOLOCK)
WHERE c.id > CAST(? AS VARCHAR(100))
  AND c.id LIKE 'CN%'                    -- <-- EDIT: your pool filter
  AND SUBSTRING(c.id, 4, 1) <> '*'       -- good ids only, no direct entries
ORDER BY c.id;
