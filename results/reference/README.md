# Reference results

The full-matrix CSV files were captured on 2026-08-14 using an enhanced local branch with source and destination port 0 fixed. `public-upstream-smoke.csv` was captured on 2026-08-17 from the pinned public commit, whose runner sprays source packets across four shortest first hops and resolves the destination CNA to port 0.

They are intentionally small. Raw `runlog/` trees ranged from roughly 0.3 GB to 2.2 GB per case and are regenerated locally rather than stored in Git.

When comparing a new run:

1. confirm `git -C external/ns-3-ub rev-parse HEAD` matches `simulator.lock.json`;
2. confirm the generated `generation-summary.json` reports 2560 links and 1,144,832 routing rows;
3. compare within the same provenance first; compare qualitative causal relationships rather than exact numbers across the historical and public-upstream datasets;
4. record RNG run, host OS, compiler, profile, and any `SIM_REF` override.
