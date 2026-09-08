"""Term 4 artefact generation: the report and the deck.

Both documents read `docs/results/`. Neither restates a number that is not in a results file,
which is the mechanism behind CLAUDE.md's rule that every figure be reproducible: if a model has
not been run, its table says so rather than carrying a remembered value.

Provenance is not decoration here. `scripts/guard_synthetic.py` blocks generated figures from
reaching a graded artefact, and it currently blocks, because the Dubai Land Department's portal
refuses automated clients from every network this project can reach. Generating anyway requires
`--draft`, and a draft stamps every synthetic figure at three levels: a banner on the cover or the
opening slide, a provenance column in every model table, and a limitations section that says which
numbers describe a stand-in. A reader cannot reach a figure without passing a label.
"""
