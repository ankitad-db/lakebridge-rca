# RCA taxonomy: how probes map to categories and verdicts

The deterministic engine runs value-difference probes on the sampled mismatches
in `details`, plus row-pattern and freshness analysis. Each probe emits signals;
the classifier aggregates them into a category, a verdict, and a confidence.

| Category | Signals that fire it | Default verdict | Typical remediation |
|----------|----------------------|-----------------|---------------------|
| `type_precision` | values equal after rounding to a smaller scale; tiny relative diff | Migration-induced | Preserve `DECIMAL(p,s)`; avoid mapping to `DOUBLE`/lower scale |
| `transpilation` | target = source rounded to whole units; risky functions in transform SQL | Migration-induced | Fix translated SQL (ROUND mode, `DATE_TRUNC('week')`, `SPLIT_PART`, ...) |
| `timezone` | constant whole-hour(+half-hour) offset across rows | Migration-induced | Normalize `TIMESTAMP_LTZ/TZ` to UTC on load |
| `string_format` | equal after trim / case-fold / Unicode NFC | Migration-induced (low severity) | Add TRIM/normalization or align collation |
| `null_boolean` | NULL vs empty string; equivalent boolean encodings (`Y/N` vs `true/false`) | Migration-induced | Map NULL/empty and boolean encodings explicitly |
| `volume_missing` | rows in source, absent in target | Migration-induced | Check load filter/watermark; back-fill; make idempotent |
| `volume_extra` | rows in target, absent in source | Migration-induced | Fix fan-out join / de-duplicate |
| `semi_structured` | JSON/VARIANT semantically equal, serialized differently | Benign | None (or canonicalize before reconciling) |
| `upstream_drift` | NULL in source but populated in target; large timestamp/snapshot gap; unexplained partial-column mismatch on a table with snapshot drift | Genuine data difference | Route to the data owner; align snapshot times |
| `unknown` | no deterministic probe fired | Needs review | Live drill-down query |

## Key principle

`upstream_drift` / genuine-data is what keeps this honest: not every mismatch is a
migration defect. When the **source** is NULL/absent (or a stale snapshot) and the
target has values, that is a real upstream data difference to route to the data
owner — not a migration bug to fix. Always verify provenance with a source-side
query before finalizing.
