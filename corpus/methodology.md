---
id: methodology
kind: community
title: How YIELDMAP computes what it shows
source: This project
source_url: https://github.com/krish2105/YIELDMAP-AI-in-Finance
status: verified
retrieved: written as part of the project
lang: en
---

# How YIELDMAP computes what it shows

## Valuation

A gradient-boosted regressor predicts log price per square metre from area, property type, bedroom
count, floor area, off-plan status and time. It is trained on everything before the most recent
twelve months and scored on those twelve months, so it is never tested on data it has seen.
Predictions are transformed back from log space with Duan's smearing correction, without which they
would be biased low. Accuracy is reported against two references: the median price per square metre
for the same area, type and bedroom count, and an estimate of the data's own irreducible noise.

## Price index

A repeat-sales index compares each property against itself, so changes in the mix of what sold do
not appear as price movement. The estimator is Bailey-Muth-Nourse weighted least squares on period
dummies, weighted by inverse holding period. It is published only across a connected set of
periods, because the relative level of two period chains that share no repeat sale is not
identified by the data.

## Yield

Gross yield is the median annual Ejari rent for a cell divided by the median sale price for the
same cell over the same window. Net yield takes rent after vacancy, subtracts the service charge,
management fee, maintenance and the purchase costs amortised over an assumed holding period, and
divides by the full acquisition cost including fees. Every input is editable.

## Risk

A weighted blend of off-plan exposure, developer concentration, price volatility, illiquidity and
anomaly density, each scaled to a bounded range and clipped rather than extrapolated. The
components are always published alongside the total.

## Anomalies

Three independent signals: an isolation forest on price residuals against the area and type norm, a
rapid-resale rule for properties changing hands within ninety days, and a round-number rule for
prices landing exactly on large round figures. Every flag names the rule that fired.

## Sample size and confidence

Every figure carries the number of observations behind it. Cells below the minimum are not
published as numbers at all; they are shown as insufficient data. A yield built from two hundred
sales and three tenancies is a three-observation figure, and is treated as one.
