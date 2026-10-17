# Analysis notes

Commands for these analyses are in the
[reproduction guide](../reproduce/REPRODUCE.md#rq3-diagnostics-and-django-figures).

## Django figures and region statistics

The Django scripts select all 849 Django issues.

### Figure 4: representation geometry

Both panels use 256-dimensional representations from the encoder and projection
head. The untrained reference, labeled M0 in the plot, uses the pretrained
backbone with a randomly initialized projection head. UMAP is fitted on these
hunk representations and transforms the trained M2 hunks into the same space.
REQ, TEST, and ORIG background positions remain those of the untrained reference.
The M0 ranking baseline uses 768-dimensional mean-pooled backbone embeddings
with the projection head bypassed.

### Figure 5: diagnostic similarities

REQ similarity compares each hunk with its requirement. TEST similarity compares
the hunk with the normalized mean of its issue's test embeddings and determines
the point's color intensity. ORIG similarity compares the hunk with the normalized
mean of its matched source-unit embeddings. When no source unit matches, it uses
the normalized mean of the issue's first 16 available source units. Missing tests
or an issue without source units contribute zero.

### Ranking and region statistics

Ranking uses the maximum hunk similarity across individual tests. Its ORIG term
uses matched source units and contributes zero when none matches. The reported
five-region statistics use these EEL score components. Region percentages are
computed among retained T1/T2 hunks. The per-hunk scores and run log are in
[`region_analysis.json`](../../Data/Evaluation/training_variants/region_analysis.json)
and [`region_analysis.log`](../../Data/Evaluation/training_variants/region_analysis.log).

## Hunk similarity

This analysis compares changed lines using UniXCoder cosine similarity.
Retained hunks are paired with reference hunks in the same file less than
20 lines apart. Pairing first uses unique references; the remaining 622 hunks
use the nearest same-file reference. T3 hunks use the nearest same-file
reference, with a closest-path fallback for one hunk. The random control uses
another issue in the same repository, with seed 0.

Commands are in the [reproduction guide](../reproduce/REPRODUCE.md#hunk-similarity).
