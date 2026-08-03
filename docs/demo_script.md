# Synthetic Contract Intelligence Tool-Layer POC — Demo Script

Deterministic offline demo (`USE_OFFLINE_MOCKS=true`).  
Current path: Streamlit → Flask `/api/messages` → offline cognitive router → FastMCP tools → synthetic Gold fixtures.

This is **not** an Azure AI Foundry-first runtime.

---

## 1. Show contracts for AlphaTech Services

| Item | Detail |
| --- | --- |
| **Expected tool** | `search_contracts(vendor="AlphaTech Services")` |
| **Expected behavior** | Structured metadata list (not Azure AI Search docs). Stable fields including contract_id, vendor_name, dates, ACV, payment_terms_days, rate_card_on_file. |
| **Sample expected output** | Rows for `C-1001`, `C-1002`, `C-1003` under vendor AlphaTech Services. |
| **Success looks like** | At least 3 AlphaTech contracts with key commercial fields; source cited as `synthetic_gold_contracts`. |

---

## 2. Show details for Contract C-1001

| Item | Detail |
| --- | --- |
| **Expected tool** | `get_contract_profile(contract_id="C-1001")` |
| **Expected behavior** | One normalized profile with missing_fields array. |
| **Sample expected output** | Profile for C-1001 / AlphaTech Managed Services Master; ACV 120000 USD; payment_terms_days=30; rate_card_on_file=true; missing_fields empty or listed. |
| **Success looks like** | Single-contract profile, not a multi-row search dump. |

---

## 3. Compare C-1001 and C-1002

| Item | Detail |
| --- | --- |
| **Expected tool** | `compare_contracts(contract_refs="C-1001,C-1002")` |
| **Expected behavior** | Field-level compare + `## Recommendation` style decision notes when LLM path is used; offline router emits comparison tables / ranking notes. |
| **Sample expected output** | Differences on type (Managed Services vs Professional Services), ACV (120000 vs 240000), payment terms (30 vs 90), rate card flags. |
| **Success looks like** | Clear side-by-side deltas and an explicit preference / risk call. |

---

## 4. Which contracts need action in next 90 days?

| Item | Detail |
| --- | --- |
| **Expected tool** | `get_expiring_contracts(days_ahead≈90..365)` |
| **Expected behavior** | Near-term expirations / renewal action list from synthetic Gold dates. |
| **Sample expected output** | Includes AlphaTech C-1001/C-1002/C-1003 when inside the lookahead window used by the offline router. |
| **Success looks like** | Actionable expiry list with vendor + dates (not invoice payments). |

---

## 5. Which contracts have missing renewal information?

| Item | Detail |
| --- | --- |
| **Expected tool** | `check_missing_contract_fields` and/or `search_contracts` + profile missing_fields |
| **Expected behavior** | Surfaces contracts with blank/null RenewalDate (demo seed: `C-1003`). |
| **Sample expected output** | C-1003 AlphaTech Support Retainer flagged for missing RenewalDate (and possibly ContractOwner). |
| **Success looks like** | Explicit missing-field list; no fabricated renewal dates. |

---

## 6. Are there overlapping contracts for the same vendor?

| Item | Detail |
| --- | --- |
| **Expected tool** | `find_overlaps` |
| **Expected behavior** | Same-vendor effective→expiration window overlaps from structured Gold data. |
| **Sample expected output** | AlphaTech pair `C-1001` vs `C-1002` with overlap_start/overlap_end and why_flagged. |
| **Success looks like** | Deliberate overlap cases returned with stable fields; source `synthetic_gold_contracts`. |

---

## 7. Which contracts have unusual payment terms or high rates?

| Item | Detail |
| --- | --- |
| **Expected tool** | `explain_contract_risk` |
| **Expected behavior** | Structured known_facts / computed_risks / missing_data / recommended_review_action. No invented risks. |
| **Sample expected output** | C-1002 includes unusual_payment_terms (Net 90), high_contract_value_outlier and/or missing_rate_card, plus overlapping_contract where applicable. |
| **Success looks like** | Grounded risk explanation separating facts from computed flags. |

---

## 8. Can you show invoice spend also?

| Item | Detail |
| --- | --- |
| **Expected tool** | **None** (hard guardrail before tool selection) |
| **Expected response behavior** | Exact refusal; must not call `get_vendor_spend_summary` or return contract-value rollups as invoices. |
| **Expected answer (exact)** | `Invoice/spend data is not part of this synthetic contract intelligence POC. This requires a separate data-linkage POC.` |
| **Success looks like** | Only that sentence (or that sentence as the full reply). |

---

## How to run (offline)

```bash
export USE_OFFLINE_MOCKS=true
# start mcp-backed Flask agent + Streamlit as usual, or:
cd copilot_agent && USE_OFFLINE_MOCKS=true python - <<'PY'
import asyncio, os
os.environ['USE_OFFLINE_MOCKS']='true'
from offline_router import run_offline_turn
print(asyncio.run(run_offline_turn('Can you show invoice spend also?')))
PY
```
