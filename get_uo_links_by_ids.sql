/* Ultimate-owner links for a set of ids.
   Returns, for each input id, the UO(s) it is attached to. Used to detect
   "Same UO" between an OriginalId and its MatchedId. */
SELECT DISTINCT
    l.ChildId,
    l.ParentId
FROM bvdaffils.dbo.UO_links AS l WITH (NOLOCK)
JOIN #TempIds AS t ON t.Id = l.ChildId;
