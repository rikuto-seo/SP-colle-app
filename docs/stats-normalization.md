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

## Remaining scope

No model or migration changes are needed. Production DB access, migrations,
deployment and mapping backfill are outside this change. Real DB mapping coverage
and large-catalog performance still need staging verification. A persistent
administrator review queue, import-time coverage checks and ambiguous-label
handling remain later work; unclassified owned quantities are visible now.
