# Benchmark fixtures

`network.npz` (+ `network.npz.json`) is the compiled catchment network
**`16811181e3006ac9`** for `delhi-barapullah` (the Kushak Nallah and Barapulla Nala drain
system, South Delhi), the network every benchmark number in `bench/results/` was
measured on.

It is committed here, and only here, so that CI can run the benchmark gate on
the real catchment rather than on a synthetic toy. Everywhere else the network is
a build product (`data/artifacts/` is git-ignored, GC-6): the version is a content
hash, so this copy can be checked against a fresh build with

```bash
uv run python -m upstream_kernel.compile.cli --skip-db --out /tmp/network.npz
# prints network_version=16811181e3006ac9 when built from the same OSM extract
```

CI builds the physics tables from this file and the kernel's current parameters
on every run, so a parameter change is benchmarked, never a stale table.

All ten outfalls in it are synthetic (`is_synthetic: true`, PRD R2).

**Attribution.** Drain geometry and zones derived from OpenStreetMap data,
© OpenStreetMap contributors, available under the
[Open Database Licence](https://www.openstreetmap.org/copyright).
