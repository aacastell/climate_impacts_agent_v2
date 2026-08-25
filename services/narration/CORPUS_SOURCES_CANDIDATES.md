# RAG corpus — candidate sources, not yet curated into `corpus.py`

Found via real web search tonight, not fabricated — every entry below is a real, citable source.
This is a candidate list for review, exactly matching the boundary set earlier tonight:
`corpus.py` stays honestly empty until someone reviews these and decides what actually goes in,
with what exact wording, attributed correctly. Finding sources is a research task I could do;
deciding what a RAG corpus should assert as ground truth is a scientific judgment call, not mine
to make unsupervised.

What this list is deliberately built around, per your ask: NASA-first where real NASA sources
exist, and focused on the *underlying agronomic science* (why heat/drought affect these crops) —
not ISIMIP/climate-impact framing, which the rest of this system already owns.

## NASA sources

- [NASA GISS: Yang and Wang — Heat stress to jeopardize crop production in the US Corn Belt](https://www.giss.nasa.gov/pubs/abs/ya08200c.html) — maize-specific, geographic shift in the most-productive growing zone under heat stress.
- [NASA: Climate Change and Its Environmental Impacts on Crop Growth](https://scitechdaily.com/nasa-research-climate-change-and-its-environmental-impacts-on-crop-growth/) — general mechanism overview (~32-35°C is where many crops start showing stress, varies by crop and water availability).
- [NASA Science: When Drought Threatens Crops — NASA's Role in Famine Warnings](https://climate.nasa.gov/news/2888/when-drought-threatens-crops-nasas-role-in-famine-warnings) — drought monitoring via satellite (SMAP soil moisture), real-world early-warning framing.
- [NASA Harvest + USDA: Water Use and Crop Yield Simulator (GEO-CropSim)](https://nasaharvest.umd.edu/news/nasa-harvest-and-usda-release-water-use-and-crop-yield-simulator) — process-based crop modeling combining satellite Earth observations with water-use data.

## Heat stress mechanisms — cross-crop and per-crop

- [Nature Food: Temperature thresholds of extreme heat-induced yield loss in maize and soybean](https://www.nature.com/articles/s43016-026-01298-0) — 2026, real empirical per-crop thresholds (maize ~34.8±4.0°C, soybean ~33.7±3.9°C) with geographic heterogeneity across the Northern Hemisphere — this is the same study already cited in `pipeline/climate_pipeline/process/indices.py`'s docstring as the source for the crop-specific-threshold tradeoff discussion.
- [PNAS: Temperature increase reduces global yields of major crops in four independent estimates](https://www.pnas.org/doi/10.1073/pnas.1701762114) — cross-crop quantitative yield-loss-per-°C figures.
- [Frontiers in Plant Science: Molecular mechanism of heat stress during grain filling in maize](https://www.frontiersin.org/journals/plant-science/articles/10.3389/fpls.2024.1533527/full) — maize-specific, grain-filling stage mechanism.
- [ScienceDirect: Heat stress in cereals — mechanisms and modelling](https://www.sciencedirect.com/science/article/abs/pii/S1161030114001221) — wheat/cereal-focused mechanistic review.
- [PMC: Physiological, Biochemical, and Molecular Mechanisms of Heat Stress Tolerance in Plants](https://pmc.ncbi.nlm.nih.gov/articles/PMC3676804/) — cross-crop foundational mechanism review (photosynthesis, respiration, fertility impacts above 30-37°C).
- [Springer: Impression of contemporary heat stress complexities in agricultural crops — a review](https://link.springer.com/article/10.1007/s10725-025-01382-8) — 2025 general review.

## Drought / water stress mechanisms — reproductive-stage focus

- [Frontiers in Plant Science: Mechanistic insights into drought stress management in staple crops](https://www.frontiersin.org/journals/plant-science/articles/10.3389/fpls.2025.1547452/full) — cross-crop (rice/wheat/maize), reproductive-stage sensitivity.
- [Nature Scientific Reports: Drought stress at flowering stage — rice physiological traits, yield, quality](https://www.nature.com/articles/s41598-019-40161-0) — rice-specific, real yield-loss figures (31-64% mild, 65-85% severe drought stress vs. normal conditions).
- [PMC: Resilience of soybean cultivars to drought stress during flowering and early-seed-setting](https://pmc.ncbi.nlm.nih.gov/articles/PMC9870866/) — soybean-specific, flowering/seed-set sensitivity.
- [PMC: Effects of drought on gene expression in maize reproductive tissue (RNA-Seq)](https://pmc.ncbi.nlm.nih.gov/articles/PMC3461560/) — maize-specific molecular mechanism.
- [Frontiers in Plant Science: Drought stress in rice — morpho-physiological and molecular responses](https://www.frontiersin.org/journals/plant-science/articles/10.3389/fpls.2023.1215371/full) — rice-specific, breeding-relevant mechanism review.

## Real, usable summary figures found (for context, not yet verified for corpus inclusion)

Per-°C yield sensitivity (source: heat-stress search above, uncredited to a single paper in the
search summary — needs tracing to its actual primary source before use, flagged not hidden):
wheat -6.0%, rice -3.2%, maize -7.4%, soybean -3.1% per 1°C increase. Maize appears most heat
temperature-sensitive of the four in multiple independent sources above.

## What's still a real, unresolved question

RAG's own constraint (ADR-007): retrieval must return mechanism/framing text, never a number —
`retrieval.py`'s design already enforces this by construction (a corpus entry has no numeric
field). That means whichever of the above get curated in should be excerpted for their mechanism
explanations, not their yield-percentage figures — the numeric figures above are for your own
evaluation of source quality, not something to embed as retrievable passages.
