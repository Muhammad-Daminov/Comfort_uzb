# ADR-008 — Cyrillic/Latin Search Normalization

**Status:** Accepted
**Owner:** backend-core
**Domain:** Search / Catalog
**Last updated:** 2026-08-17
**Source:** [00_MASTER_TZ.md](../00_MASTER_TZ.md) §1 ADR-8, §6.5

## Context
Uzbek-market users type car model names in whatever script/spelling is at hand: `Nexia`, `Neksiya`, `Нексия`, `nexiya`. Without normalization, search recall is unacceptably low — this is called out as critical, not a nice-to-have.

## Decision
Three-part mechanism, applied identically at write time and query time:
1. **Normalization function**: Cyrillic→Latin transliteration table (н→n, х→x, ш→sh, ч→ch, ў→o, қ→q, ғ→g, ҳ→h, ц→ts, я→ya, …), Uzbek apostrophe variants (`oʻ o' o\` ў` → `o`, `gʻ g' g\`` → `g`), lowercase, whitespace/punctuation collapsed.
2. **Trigram index**: `pg_trgm` extension, `products.search_text` column, `gin_trgm_ops` GIN index.
3. **Alias table**: `search_aliases(alias, canonical, entity_type)` for colloquial spellings (`neksiya`→`nexia`).

Match order: alias exact match → exact match → trigram similarity ≥ 0.3.

## Consequences
- The normalization function must be a single shared implementation called both when writing `search_text` (on product create/update) and when parsing a search query — two divergent implementations would silently break matching.
- `database` owns the `pg_trgm` extension and index (§18.2); `backend-core` owns the normalization function and alias-table population/maintenance.
- Populating `search_aliases` for common car-model misspellings is an ongoing content task, not a one-time migration — flag to `docs`/`architect` if it needs a maintenance owner.
