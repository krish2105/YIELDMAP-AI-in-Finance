---
id: dld_fees
kind: law
title: Transaction fees on a Dubai property purchase
source: Dubai Land Department fee schedule
source_url: https://dubailand.gov.ae/en/services/
status: unverified
retrieved: not yet archived — the ingest job could not reach the publisher
lang: en
---

# Transaction fees on a Dubai property purchase

Buying property in Dubai costs more than the purchase price. The additional costs fall into four
groups, and together they are the reason a gross yield overstates the return an owner actually
receives.

## Transfer fee

The Dubai Land Department charges a transfer fee on registration, calculated as a percentage of the
purchase price. It is conventionally described as being shared between buyer and seller, but in
practice the buyer customarily bears it in full. YIELDMAP assumes the buyer pays it in full, which
is the conservative assumption for a buyer's yield calculation.

## Registration and trustee fees

A registration charge applies on transfer, along with trustee office fees. These are flat amounts
rather than percentages, so they matter proportionally more on a smaller purchase.

## Mortgage registration

Where the purchase is financed, registering the mortgage attracts a further fee calculated on the
loan amount, plus an administrative charge.

## Agency commission

Buyer-side agency commission is a market convention rather than a regulated fee and is negotiable.

## How YIELDMAP uses these

All of these appear in `config/assumptions.yaml` and `config/mortgage.yaml` with a status field.
Fields marked `unverified` are shown in the interface as editable assumptions rather than as rules,
and the net yield and cash-flow projections recompute when they are changed. The values used are
widely reported figures; they are not asserted as verified until the ingest job archives the
publisher's own schedule.
