# Statistics and photo completion

Completion and quantities measure different things:

- A required photo is identified by `Photo.id`. Group completion by member ID
  and costume ID, never by a normalized type or costume name.
- A photo is owned only when that user's `UserPhoto.quantity > 0`.
- Completion is owned required Photo IDs / all required Photo IDs. Multiple
  copies and multiple photos with the same classification cannot change the
  denominator. Costume progress applies the same rule across its members.
- Total ownership and type statistics sum actual positive quantities.

`services/stats_service.py` supplies the common inventory and completion
calculation for statistics, member details and shared statistics. The collection
index counts distinct owned Photo IDs in SQL and exposes member/costume IDs in
card data. Missing photos use the same positive-quantity ownership rule.

## Classification and original labels

Classification still uses the existing DB-first resolver and legacy fallback.
No new number inference, master-data rewrite or bulk mapping migration is added.

`build_stats_data()` returns:

- `type_stats`: exactly the four ordered keys ヨリ, チュウ, ヒキ, 座り, including
  zero totals.
- `unclassified_quantity`: all positive quantities whose resolved value is not
  one of the four classifications.
- `unclassified_stats`: quantities and owned Photo counts grouped by costume ID
  and PhotoType ID, preserving the original type and costume labels.
- `comp_stats` and `progress_list`: photo-based counts, with `costume_id` and
  `costume_label`. Same-name costumes get an ID suffix for disambiguation.
- `member_stats` and `comp_stats` are keyed by member ID, not name.
  `ordered_members` contains `{id, name}` records; `member_names` supplies labels.
  Rankings also include `member_id` so equal display names remain independent.

The invariant is:

```text
sum(type_stats.values()) + unclassified_quantity == sum(member_stats.values())
```

`templates/_type_stats.html` displays the four classifications and a separate
unclassified section in both private and public statistics. The shared page
separates total copies from owned distinct photos and its photo-based percentage.
Existing public-share authorization checks remain in place.

Collection labels, add choices, submissions and AJAX detail labels retain the
original `PhotoType.name`. Missing rows now include `photo_id`, `costume_id`,
the original `type` and `normalized_type` separately; the page shows identifiers
so different photos remain distinguishable even if their classifications match.

## Member identity and bounded responses

The stats UI loads details through `/stats/member/<group>/id/<member_id>`.
The old name URL remains valid only for a unique name in that group; ambiguous
names return 409, missing/out-of-group IDs return 404. Missing-photo grouping and
filters use member/costume IDs (`member_id` and `costume_id` query parameters).

Completion and quantity calculations now aggregate in SQL instead of loading
every Photo into Python. Counts still represent distinct Photo identity because
the user/photo join is unique, never normalized classifications. The shared
stats catalog renders 100 photos per page in Photo ID order; summary counts and
quantities always cover the entire group, independent of the current page.
No cross-request cache is introduced.

Legacy add forms send names. An ambiguous Photo match now returns 409 instead
of updating the first row. Callers can provide `member_id` and `costume_id` to
disambiguate while keeping the original label fields. The existing add dropdown
UI has not been converted to ID values; selecting duplicate-name alternatives
through that UI remains a later enhancement, with ambiguous writes blocked now.

## Validation

Run the isolated SQLite tests without importing `app.py` or production services:

```text
python -m unittest discover -s tests
```

The normalization suite covers partial same-classification ownership, completion
only after every Photo is owned, zero/negative quantities, duplicate copies,
AJAX updates, original numeric/decorated labels, unclassified reconciliation,
same-name costumes, empty catalogs, and public-share privacy/group boundaries.
The negative-quantity case temporarily disables checks only in memory-only
SQLite to emulate invalid legacy data; production constraints are unchanged.

Synthetic performance results and methods are in `stats-performance.md` and
`stats-performance-results.json`. Run the optional browser regression with:

```text
python tests/check_photo_type_order_browser.py --browser PATH_TO_CHROME
python tests/check_stats_browser.py --browser PATH_TO_CHROME
```

## Remaining scope

No model or migration changes are needed. Production DB access, migrations,
deployment and mapping backfill are outside this change. Real DB mapping coverage
and PostgreSQL/concurrent-load performance still need staging verification. A persistent
administrator review queue, import-time coverage checks and ambiguous-label
handling remain later work; unclassified owned quantities are visible now.
