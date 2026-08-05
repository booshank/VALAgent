# Synthetic Contract Intelligence Tool-Layer POC — Demo Script

Deterministic offline demo (`USE_OFFLINE_MOCKS=true`).  
Current path: Streamlit → Flask `/api/messages` → offline cognitive router → FastMCP tools → LinkSquares sample fixtures.

Fixture sources:
- `mcp_server/LinSquare_Contracts_100_Updated_30bb.json` (100 contracts)
- `mcp_server/agreement_9a06.json` (shared agreement metadata)

This is **not** an Azure AI Foundry-first runtime.

---

## 1. Show contracts for Microsoft

| Item | Detail |
| --- | --- |
| **Expected tool** | `search_contracts(vendor="Microsoft")` |
| **Expected behavior** | Structured metadata list (not Azure AI Search docs). Stable fields including contract_id, vendor_name, dates, ACV, payment_terms_days, rate_card_on_file. |
| **Sample expected output** | Multiple Microsoft rows (e.g. `CON-0002`, `CON-0006`, `CON-0010`). |
| **Success looks like** | Structured Microsoft contracts with commercial fields; source cited as `synthetic_gold_contracts`. |

---

## 2. Show details for Contract CON-0002

| Item | Detail |
| --- | --- |
| **Expected tool** | `get_contract_profile(contract_id="CON-0002")` |
| **Expected behavior** | One normalized profile with missing_fields array. |
| **Sample expected output** | Profile for CON-0002 / Microsoft Agreement 2; rate_card_on_file=true; ActionRequired=30 Days. |
| **Success looks like** | Single-contract profile, not a multi-row search dump. |

---

## 3. Compare CON-0001 and CON-0002

| Item | Detail |
| --- | --- |
| **Expected tool** | `compare_contracts(contract_refs="CON-0001,CON-0002")` |
| **Expected behavior** | Field-level compare + `## Recommendation` style decision notes when LLM path is used; offline router emits comparison tables / ranking notes. |
| **Sample expected output** | Differences on vendor (AWS vs Microsoft), payment terms, contract value, OpCo/business unit. |
| **Success looks like** | Clear side-by-side deltas and an explicit preference / risk call. |

---

## 4. Which contracts need action in next 90 days?

| Item | Detail |
| --- | --- |
| **Expected tool** | `get_expiring_contracts(days_ahead≈90..365)` |
| **Expected behavior** | Near-term expirations / renewal action list from projected LinkSquares renewal dates. |
| **Sample expected output** | Includes ActionRequired 30/60/90 Day contracts such as CON-0001..CON-0015 when inside the lookahead window. |
| **Success looks like** | Actionable expiry list with vendor + dates (not invoice payments). |

---

## 5. Which contracts have missing renewal information?

| Item | Detail |
| --- | --- |
| **Expected tool** | `check_missing_contract_fields` and/or `search_contracts` + profile missing_fields |
| **Expected behavior** | Surfaces contracts with blank/null RenewalDate (sample seed: `CON-0016`..`CON-0020`). |
| **Sample expected output** | Those IDs flagged for missing RenewalDate / EffectiveDate / ExpirationDate. |
| **Success looks like** | Explicit missing-field list; no fabricated renewal dates. |

---

## 6. Are there overlapping contracts for the same vendor?

| Item | Detail |
| --- | --- |
| **Expected tool** | `find_overlaps` |
| **Expected behavior** | Same-vendor overlaps where LinkSquares `OverlapFlag=Yes` on both contracts. |
| **Sample expected output** | Microsoft `CON-0024` vs `CON-0029`; also Oracle / AWS / Accenture flagged pairs. |
| **Success looks like** | Flagged overlap cases with stable fields; source `synthetic_gold_contracts`. |

---

## 7. Which contracts have unusual payment terms or high rates?

| Item | Detail |
| --- | --- |
| **Expected tool** | `explain_contract_risk` |
| **Expected behavior** | Structured known_facts / computed_risks / missing_data / recommended_review_action. No invented risks. |
| **Sample expected output** | `CON-0011` (Cisco, Net 180) includes unusual_payment_terms; overlap-flagged IDs may also show overlapping_contract. |
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
