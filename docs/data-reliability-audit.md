# Price Data Reliability Audit

## Current reliability flow

```text
Store response / local snapshot
  -> Provider record parsing
  -> Catalog identity check
  -> normalized StoreProduct validation
  -> accepted product or collection_rejections quarantine
  -> current StoreProduct + change-only price_history
  -> comparable-offer and freshness filters
  -> price API / recommendation / alert
```

## Problems found and fixed

### Game identity and comparable offers

- A Provider product must match the Catalog `(Store, productId, gameId)` mapping.
- An existing Store product cannot be reassigned to another Game.
- Region, Edition and OfferType must match the Catalog identity.
- Default comparison and default alerts share the same criteria:
  `KR + Standard + BaseGame + KRW`.
- Platform native/compatible filtering remains independent from Store identity.
- DLC, Bundle, Subscription and Deluxe products cannot become the default cheapest
  offer or trigger a default base-game alert.

### Price validation

- Prices are integer KRW values and must be between 0 and 100,000,000.
- Explicit purchasable zero is accepted as a free offer.
- Missing or malformed prices are rejected instead of being converted to zero.
- Current price cannot exceed regular price.
- Discount percentage must agree with regular/current prices within one percentage
  point of Store rounding.
- Unsupported currency, region, platform and Store-specific raw fields are rejected.
- Google Play micros must convert to KRW without precision loss.

### Rejection isolation and observability

- An identifiable malformed Provider row or block is quarantined without discarding
  valid records from the same file.
- Normalized validation failures are quarantined per record.
- `collection_rejections` stores Store, Game, product ID, reason and timestamp.
- `crawl_runs` records accepted, rejected, failed and retry counts plus error text.
- Collection summary counters are exposed through the API and Web UI.

### Price-history integrity

- Unchanged product state does not append history.
- `(Store, productId, observedAt)` is unique.
- The same state at the same timestamp is idempotent.
- A conflicting state at the same timestamp is rejected.
- Out-of-order observations cannot overwrite the current product state.
- Legacy timestamp duplicates are preserved in `price_history_conflicts` during
  migration while the latest row remains active.
- Unavailable observations remain auditable but are excluded from lowest, highest,
  average, trend, recommendation and alert statistics.

### Freshness and collection reliability

- Each product tracks `lastCheckedAt` and `lastSuccessfulCheckAt`.
- A failed check updates only the attempted-check timestamp.
- A price becomes stale 48 hours after the last successful check.
- Stale products remain visible with a warning, but are excluded from cheapest,
  recommendation and alert decisions.
- Permanent collection errors are not retried.
- Transient errors use bounded exponential backoff.
- Steam HTTP 408/429/5xx and timeouts are transient; malformed data and other 4xx
  responses are permanent. `Retry-After` is honored when numeric.
- Failure of one Store does not stop other Store Providers.

## Automated coverage

Unit and repository integration tests cover:

- duplicate and unchanged observations;
- same-timestamp conflicts and out-of-order observations;
- invalid, excessive and wrong-currency prices;
- discount consistency and explicit free prices;
- stale prices and failed freshness checks;
- Provider partial failure, permanent failure and transient retry/backoff;
- DLC, Bundle, Subscription and Deluxe isolation;
- comparable and non-comparable offers;
- historical-low calculation using purchasable observations only;
- safe schema migration and conflict preservation.

`data_reliability_e2e` runs the CLI collector twice with one valid and one malformed
Epic block, starts the real API, and verifies quarantine counters, current comparable
prices, freshness and change-only history behavior.

## Remaining risks

### P1

- Steam, Epic, Nintendo, Google Play and Apple have live network collectors. Their
  parsing and failure behavior is covered by deterministic fixtures; Epic production
  collection can still be rejected by Store-side Cloudflare policy.
- Catalog mappings are manually curated. Steam verifies the returned app ID, but does
  not yet verify Store product type/name against an independently reviewed mapping.
- A malformed raw row with no recoverable Game ID cannot be attached to a game-scoped
  crawl rejection; it is retained only as a Provider parsing concern.
- Steam free-to-play responses without `price_overview` are currently treated as
  missing price. Explicit normalized zero is supported, but live free-game semantics
  need a separate source signal before adding such products.
- The 48-hour stale threshold is global. Stores with different collection schedules
  may eventually need per-Provider thresholds.
- Quarantine detail is stored in DB, while the public API currently exposes summary
  counts rather than individual rejected records.

### P2

- KR/KRW is the only supported region/currency. Cross-currency comparison remains
  intentionally unsupported until an exchange-rate policy exists.
- Edition and OfferType enums cover current Catalog needs, not every future Store label.
- The fixed 100,000,000 KRW upper bound and one-point discount rounding tolerance may
  need configuration if product types broaden.
- Edition/OfferType-specific alerts are not yet user-configurable. The default criteria
  are shared so those fields can later be added to `alert_rules` without changing the
  price evaluation model.
