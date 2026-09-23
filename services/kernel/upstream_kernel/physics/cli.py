"""Build the versioned physics tables and publish ParametersVersionPublished.

Usage:
    python -m upstream_kernel.physics.cli --network data/artifacts/network.npz
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import uuid

import psycopg
from psycopg.types.json import Jsonb

from ..compile.loader import load_network
from .params import default_params
from .tables import build_tables, save_tables


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--network", default="data/artifacts/network.npz")
    ap.add_argument("--out", default="data/artifacts/tables.npz")
    ap.add_argument("--skip-db", action="store_true",
                    help="build and save the tables only; do not append to the log")
    a = ap.parse_args()

    net = load_network(a.network)
    params = default_params()
    tables = build_tables(net, params)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    save_tables(tables, a.out)

    if not a.skip_db:
        with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as c, c.cursor() as cur:
            cur.execute(
                "SELECT append_event(%s,'live',%s,'ParametersVersionPublished',1,%s,%s,NULL,NULL)",
                (uuid.uuid4(), net.catchment_id, dt.datetime.now(dt.UTC),
                 Jsonb({"params_version": params.version,
                        "network_version": net.version})))

    print(f"params_version={params.version} network_version={net.version} "
          f"tau_shape={tables.tau.shape}")


if __name__ == "__main__":
    main()
