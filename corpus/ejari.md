---
id: ejari
kind: rera
title: Ejari tenancy registration
source: Dubai Land Department guidance on Ejari
source_url: https://dubailand.gov.ae/en/eservices/
status: unverified
retrieved: not yet archived — the ingest job could not reach the publisher
lang: en
---

# Ejari tenancy registration

Ejari is the Dubai Land Department system through which tenancy contracts are registered. Every
tenancy in Dubai is required to be registered, and registration is what makes a contract
recognised for utility connections, visa processes and disputes.

## Why it matters to this project

Ejari is the reason Dubai has public rent data at all. Because tenancies are registered centrally,
the rent actually agreed on a contract becomes part of an open dataset rather than remaining
private between landlord and tenant. That is what makes a measured yield possible: the rent side of
the calculation comes from recorded contracts, not from asking prices on a portal.

## What the data does and does not contain

The registry records the contract: the property, the period and the annual rent. It does not record
the gaps between tenancies, so **vacancy cannot be measured from the open data and has to be
assumed**. YIELDMAP's vacancy assumption is stated in `config/assumptions.yaml` and is editable.

It also records rent for the specific unit under contract. YIELDMAP's yields use the median rent
for an area, property type and bedroom count rather than the rent of a particular unit, so a yield
shown for a cell describes that cell rather than any individual property.
