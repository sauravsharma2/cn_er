/* Ownership links (parent/child) for a set of ids.
   Both directions are collected so the caller can build, for each id, the
   full set of its parents and its children. #TempIds is filled by
   src/code/ownership.py (ids without the trailing '!'). */
SELECT DISTINCT
    l.ParentId,
    l.ChildId
FROM bvdaffils.dbo.Links AS l WITH (NOLOCK)
JOIN #TempIds AS t ON t.Id = l.ParentId
WHERE l.Type = 1

UNION

SELECT DISTINCT
    l.ParentId,
    l.ChildId
FROM bvdaffils.dbo.Links AS l WITH (NOLOCK)
JOIN #TempIds AS t ON t.Id = l.ChildId
WHERE l.Type = 1;
