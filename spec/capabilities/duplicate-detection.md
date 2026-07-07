# Capability: Duplicate Detection (C10)

## What It Does
Detects re-uploads of the same file by content hash and filename, returning a resolvable 409.

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| file bytes | bytes | upload | yes |
| filename | string | upload | yes |
| force | bool | query | no |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| 409 error | JSON | `{code:"duplicate_dataset", match_type, existing_*}` |

## External Calls
| System | Operation | On Failure |
|--------|-----------|------------|
| SQLite | look up `content_hash` / filename | none |

## Business Rules
- Compute sha256 of bytes; a hash match (or filename match) on an existing dataset → 409 with `match_type` + existing dataset info.
- `force=true` bypasses the check and creates a new dataset.
- **C38 extension (Phase 12):** sheets imported from a multi-sheet Excel workbook dedup **per sheet** — `content_hash` is the sha256 of the sheet's canonical CSV serialization (not the workbook bytes) and `filename` is `workbook.xlsx — Sheet`, so sibling sheets never block each other; duplicates surface as a per-sheet `status:"duplicate"` result on `POST /upload/sheets` (same `match_type`/`existing_*` fields, not an HTTP 409). See [multi-sheet-excel.md](multi-sheet-excel.md).

## Success Criteria
- [ ] Uploading identical bytes twice returns 409 `duplicate_dataset` with `match_type` and the existing dataset id.
- [ ] The same upload with `force=true` returns 200 and creates a second dataset.
