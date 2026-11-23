/* Full rows for the matched pool ids. #TempIds is filled by data_extraction.load_temp_ids.
   No entries/pool filter here - the ids are already chosen. */
SELECT
    c.id                                        AS id,
    c.name                                      AS name,
    CAST(c.nativename AS VARBINARY(MAX))        AS native_name,
    CAST(c.address    AS VARBINARY(MAX))        AS address,
    CAST(c.pccity     AS VARBINARY(MAX))        AS pccity,
    c.postcode                                  AS postcode
FROM bvdaffils.dbo.companies c WITH (NOLOCK)
INNER JOIN #TempIds t ON t.id = c.id;
