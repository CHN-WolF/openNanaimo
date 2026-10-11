# Event-card reward configuration

The adapter implements dedicated `C3FD/C3FE` redemption with explicitly configured reward pools. Each enabled page defines weighted single-item, item-bundle or Hans rewards. Configuration enables redemption; card drops, collection and album display remain active independently. The optional reviewed pool is installed through a separate administrative action.

## Configuration

The UTF-8 file `event-card-rewards.json` resides beside the active `game.db`, normally in `adapter_data`. The adapter reads it for each new redemption. The disabled configuration is:

```json
{
  "Version": 1,
  "Pages": []
}
```

The root object has exactly `Version` (integer **1**) and `Pages` (an array). Each page has exactly `Page` and `Rewards`: `Page` is a unique integer from 1 through 10, and `Rewards` is a nonempty array. Each reward uses exactly one of the following field sets; names are case-sensitive and unknown or duplicate fields are rejected.

| Reward form | Exact fields | Constraints and effect |
|---|---|---|
| Single item | `Code`, `Quantity`, `Weight` | `Code` is an existing shop-catalog item, not a card-catalog entry; `Quantity` is exactly 1. Grants that item. |
| Item bundle | `Bundle`, `Weight` | `Bundle` contains 1..20 distinct eligible item codes. Grants one of every listed item in a single transaction. No `Code`, `Quantity` or `Hans` fields are permitted. |
| Hans variant | `Code`, `Quantity`, `Weight`, `Hans` | `Code` must still be an eligible catalog item and `Quantity` must be 1. `Hans` is an integer in 0..1000000; a positive value grants that many Hans instead of the item, while zero uses ordinary single-item behavior. |

Eligible items include clothing, pets, pet materials, furniture and ordinary items, even when catalog purchasing is disabled. Item codes must be unique across all entries and bundle members within one page; this also applies to the validated `Code` in a Hans entry. Each `Weight` is an integer in 1..10000, and all weights on one page must sum to **10000**. Weights define the adapter reward probabilities.

The following complete configuration illustrates all three forms with catalog codes from the shipped pool:

```json
{
  "Version": 1,
  "Pages": [
    {
      "Page": 1,
      "Rewards": [
        { "Code": 15009238, "Quantity": 1, "Weight": 1000 },
        { "Bundle": [14002488, 14002489], "Weight": 7000 },
        { "Code": 46000008, "Quantity": 1, "Weight": 2000, "Hans": 200 }
      ]
    }
  ]
}
```

The Hans entry uses `Code` as its catalog-validated reward identity and grants exactly 200 Hans. Clothing rewards are resolved to the character gender; timed clothing extends its stored expiration.

The size limit is 64 KiB. Strict parsing checks required fields, duplicate keys, item eligibility and page uniqueness. Invalid or absent configuration returns a bounded failure and preserves all cards. Rewards use the ordinary-item response branch. Atomic configuration replacement keeps each redemption on one complete configuration.

Page P consumes one of each of the ten codes starting at `50000001 + (P - 1) * 10`. Pages1–4 describe secret-stage warrior series, page5 special outfits/diamonds, page6 mascot pets/outfits/items, and pages7–10 are placeholders. Redemption values come from the explicit configuration.

## Transaction and retries

- The current account/character session authorizes the request. Ten-card consumption, the selected item/bundle/Hans grant, quick-slot/furniture remapping and the receipt commit in one transaction. Every bundle member is granted in the same atomic commit.
- Insufficient capacity preserves the selected reward in `EventCardPendingDraws` and keeps all ten cards. The same pending reward remains selected when space becomes available; each retry uses the preserved selection.
- Pet rewards merge by creature family. The 15/30/90/180-day and level variants share one ownership row. A timed variant adds its authored days to the remaining term; a permanent variant makes the row permanent. Stage, level, experience, durability and gem slots stay intact. Active pets determine ownership, capacity and client inventory; a newly awarded expired pet starts a fresh term. A duplicate permanent-pet draw commits card consumption, preserves the owned pet, clears the pending draw and returns the fixed already-owned text, completing redemption. Shop purchases and inbox claims use the same merge policy; purchases against a permanent family commit their price while preserving that pet. Materials stack and consume capacity by quantity. Detailed ownership and transaction rules are maintained in knowledge topic03.
- Reward-distribution changes with pending draws require administrative review.
- A committed `(character, session, request ID)` receipt returns its original reward, including after the page is disabled. Request correlation uses a ten-second window with at most256 entries; persistent receipts enforce committed transaction identity.
- Responses carry fixed operator-facing text encoded as GBK (the client's own text encoding), at most 23 encoded bytes, followed by an explicit NUL terminator. Control characters, percent signs and characters outside GBK are rejected; longer text is truncated to the byte budget instead of failing the response.

## Validation scope

`CardUseRegression` covers parser and dispatcher behavior, session authorization, atomic inventory transactions, capacity preservation, retries and configured redemption using isolated databases and synthetic reward pools. These checks establish adapter behavior; client interaction has its own acceptance record in knowledge topic09.

## Shipped default pool

The reviewed default for both card-use flows ships with the repository at
`release/components/cards/event-card-rewards.json` (page 1-4 pools: boss pet by
duration, whole warrior outfit set, three warrior gems, whole warrior decoration
set, bread plus drink, and a direct 200-Hans grant). It is registered in
`manifest/open_release_manifest.json` and the patch allowlist, but it is **not**
auto-installed: copy it beside the active database before starting the adapter.

```powershell
Copy-Item release/components/cards/event-card-rewards.json <install-root>/adapter_data/event-card-rewards.json
```

This file uses the same three forms documented above. Installing the reviewed pool is a separate administrative action from building the adapter or enabling card drops.
