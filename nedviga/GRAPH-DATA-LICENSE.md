# Walking graph data: provenance and ODbL notice

## Dataset identity

- Artifact: `nedviga/graph_moscow.pkg`.
- Generated graph claims: Moscow pedestrian network within the configured city extract; the code documentation describes approximately 2.7M nodes / 3.1M edges.
- Generator source: internal `graph-build` script (not shipped) (osmium + numpy, single-pass stream, MOSKOW_BBOX = 55.10–56.10 / 36.90–38.20, walkable-ways filter).
- Generator output on disk: graph build artifact (`graph_moscow.pkg`).
- Bundle SHA-256 must be recorded from the release-candidate build output or recomputed before each release; do not infer provenance from the filename.
- The graph is converted from OpenStreetMap data and is database-like, not an ordinary code file.

## Provenance record (captured 2026-09-30)

- Source extract: `central-fed-district-latest.osm.pbf` (Geofabrik Central Federal District "latest" download, retrieved 2026-09-26).
- Source PBF SHA-256: `1e3616e340a90734b7da8795bf4389c143e5becdc9515897b1dd1b2c9d80d49f` (878,333,289 bytes).
- Built graph SHA-256: `d9209b65f71d00f82521201225daefe9c99ae2842b53fe90cfee465a3a83e546` (graph-build copy and `nedviga-cli/nedviga/graph_moscow.pkg` are byte-identical).
- Build result: 2,722,379 nodes / 3,133,152 edges (~200.8 MB), build log `graph-build/build_v2.log` (2026-09-26..28).
- Exact OSM replication sequence/timestamp inside the extract is not recorded (Geofabrik "latest" file); rebuilds should pin a dated extract.


## License and attribution

OpenStreetMap data is made available under the Open Data Commons Open Database License (ODbL) 1.0. OpenStreetMap requires attribution to OpenStreetMap and its contributors and a clear notice that the data is available under ODbL. See:

- Copyright / attribution: <https://www.openstreetmap.org/copyright>
- ODbL 1.0: <https://opendatacommons.org/licenses/odbl/1-0/>

Suggested notice, subject to confirming dataset provenance and the applicable share-alike scope:

> Walking graph data derived from © OpenStreetMap contributors, available under the Open Database License (ODbL) 1.0. License: <https://opendatacommons.org/licenses/odbl/1-0/>. Source and attribution: <https://www.openstreetmap.org/copyright>.

The ODbL has attribution and share-alike conditions for databases. The exact legal classification of the transformed graph, the source extract/date, whether changes are a derivative database, and the correct distribution scope have **not** been legally assessed here. The notice is a candidate disclosure, not a legal opinion or an assertion that every condition is satisfied.

## Evidence and gaps

1. Code/docs identify OSM as the graph source (`vault-docs/ARCHITECTURE.md`, `ROUTING-SELFHOSTED-PLAN.md`, `nedviga/graph.py`).
2. The original PBF/extract, download URL, timestamp, OSM replication sequence/timestamp, and a build provenance record were not located in this pass.
3. The packaged binary contains no embedded ODbL notice/source/license metadata; attribution must be supplied alongside it and in distribution documentation.
4. No legal review of ODbL share-alike/database classification has been obtained.
5. Exact source/output hashes, generator version, PBF hash, graph-generation command and build environment should be captured on future rebuilds.

## Distribution decision

**HOLD lifted 2026-09-30 by project owner acceptance.** Provenance is recorded above; the ODbL attribution notice below is mandatory in any distribution: it must ship alongside `graph_moscow.pkg` in the archive and in distribution documentation. Distribution: public release with ODbL attribution as above. Do not remove the graph (it supports the advertised offline routing path) or repackage it without updating tests, docs, archive manifest, checksums, and limitations.
