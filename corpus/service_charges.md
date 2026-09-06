---
id: service_charges
kind: service_charge
title: Service charges and the Mollak system
source: Dubai Land Department guidance on Mollak
source_url: https://dubailand.gov.ae/mydld/mollak_service_charges/
status: unverified
retrieved: not yet archived — the ingest job could not reach the publisher
lang: en
---

# Service charges and the Mollak system

Owners of property in a jointly owned development pay an annual service charge towards the upkeep
of shared areas and facilities. In Dubai these charges are administered through Mollak, the Dubai
Land Department system for owners' association accounts, which approves and publishes per-building
figures.

## Why this is the weakest number in a yield calculation

Service charges vary enormously between buildings. A tower with a large pool deck, extensive
landscaping and concierge staffing costs far more per square metre to run than a low-rise block
with none of those, and two buildings on the same street can differ by a multiple.

YIELDMAP currently applies a single per-square-metre estimate across every property, because the
per-building figures have not been loaded. This is the largest source of error in the net yield,
and it is stated as such:

- The estimate lives in `config/assumptions.yaml` with status `estimate`.
- The interface exposes it as an editable input.
- The tests assert that changing it moves the net yield.

Loading Mollak's per-building figures would replace the estimate with a measurement, and is the
single highest-value data improvement available to this project.
