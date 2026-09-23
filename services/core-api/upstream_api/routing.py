"""FR-17: assign PROBE candidates to available people and route them.

Walking times come from pgRouting over the OSM footpath graph loaded in Phase 1; the
assignment is a CP-SAT model that maximises total EC2 gain subject to time windows.
"""
from __future__ import annotations

import datetime as dt

from ortools.sat.python import cp_model
from pyproj import Geod

from .db import pool

WALK_SPEED_MPS = 1.3
DETOUR_FACTOR = 1.35          # straight-line fallback penalty when the graph has no path
_GEOD = Geod(ellps="WGS84")


def geodesic_seconds(a: tuple[float, float], b: tuple[float, float]) -> float:
    _, _, d = _GEOD.inv(a[0], a[1], b[0], b[1])
    return float(d) / WALK_SPEED_MPS


def walking_time_s(from_lonlat: tuple[float, float], to_lonlat: tuple[float, float]) -> float:
    """Walking seconds over the footpath graph.

    Two corrections the naive query needs.

    The access legs count. Each endpoint snaps to the nearest footpath vertex, and the
    routed cost covers only the vertices - not the walk from where the person actually
    is to where the path starts. The OSM footpath graph for this catchment is sparse, so
    those legs can be hundreds of metres, and ignoring them made a 3.7 km trip come back
    as 800 s of walking against a 2825 s straight line.

    And the result is floored at the geodesic: no real route beats a straight line, so
    anything below it means the graph is too sparse to describe this trip, and a
    penalised straight line is the honest answer. Returning infinity instead would
    silently drop every candidate whose nearest footpath sits in another component, and
    the assignment would come back empty with nothing to explain why.
    """
    straight = geodesic_seconds(from_lonlat, to_lonlat)
    # Both endpoints snap the same way: nearest edge, then whichever end of that edge is
    # actually closer. Taking `source` for one and `target` for the other - as the obvious
    # query does - sends a point and itself to two different vertices, and the same
    # location then costs 4877 s to walk to.
    snap = """
        SELECT CASE WHEN ST_Distance(ST_StartPoint(geom)::geography, pt::geography)
                       <= ST_Distance(ST_EndPoint(geom)::geography, pt::geography)
                    THEN source ELSE target END AS v,
               LEAST(ST_Distance(ST_StartPoint(geom)::geography, pt::geography),
                     ST_Distance(ST_EndPoint(geom)::geography, pt::geography)) AS access_m
        FROM footpath_edges, (SELECT ST_SetSRID(ST_Point(%s,%s),4326) AS pt) q
        ORDER BY geom <-> q.pt LIMIT 1
    """
    with pool.connection() as c, c.cursor() as cur:
        cur.execute(snap, (from_lonlat[0], from_lonlat[1]))
        a = cur.fetchone()
        cur.execute(snap, (to_lonlat[0], to_lonlat[1]))
        b = cur.fetchone()
        if not a or not b:
            return straight * DETOUR_FACTOR
        if a[0] == b[0]:
            routed = 0.0
        else:
            cur.execute("""SELECT sum(cost) FROM pgr_dijkstra(
                'SELECT id, source, target, cost, reverse_cost FROM footpath_edges',
                %s, %s, directed := false)""", (a[0], b[0]))
            row = cur.fetchone()
            if not row or row[0] is None:
                return straight * DETOUR_FACTOR     # different components
            routed = float(row[0])

    via_path = (routed + float(a[1] or 0.0) + float(b[1] or 0.0)) / WALK_SPEED_MPS

    # People take whichever is shorter. Forcing every trip onto the footpath graph
    # charges two access legs even when the destination is a few metres away, so a
    # volunteer already standing at the sample point was billed 2466 s to walk to it.
    # Floored at the geodesic, because nothing beats a straight line.
    return max(min(via_path, straight * DETOUR_FACTOR), straight)


def _areas_containing(volunteer_ids: list[str], points: list[tuple[float, float]]
                      ) -> set[tuple[str, int]]:
    """Which (volunteer, candidate) pairs fall inside that volunteer's coarse area.

    PRD 14.2: volunteers share a coarse area, never a live location. Resolved in one
    query rather than one per pair - the plan's per-pair lookup is O(candidates x
    volunteers) round trips.
    """
    if not volunteer_ids or not points:
        return set()
    lons = [p[0] for p in points]
    lats = [p[1] for p in points]
    with pool.connection() as c, c.cursor() as cur:
        cur.execute("""
            SELECT v.volunteer_id, p.idx
            FROM volunteers v
            CROSS JOIN LATERAL unnest(%s::float8[], %s::float8[])
                 WITH ORDINALITY AS p(lon, lat, idx)
            WHERE v.volunteer_id = ANY(%s)
              AND v.coarse_area IS NOT NULL
              AND ST_Contains(v.coarse_area, ST_SetSRID(ST_Point(p.lon, p.lat), 4326))
        """, (lons, lats, volunteer_ids))
        return {(vid, int(idx) - 1) for vid, idx in cur.fetchall()}


def assign_missions(candidates: list[dict], volunteers: list[dict], *, now: dt.datetime
                    ) -> list[tuple[str, str]]:
    if not candidates or not volunteers:
        return []

    t_now = now.timestamp()
    allowed = _areas_containing([v["volunteer_id"] for v in volunteers],
                                [c["lonlat"] for c in candidates])

    model = cp_model.CpModel()
    x: dict[tuple[int, int], cp_model.IntVar] = {}
    for i, c in enumerate(candidates):
        for j, v in enumerate(volunteers):
            if (v["volunteer_id"], i) not in allowed:
                continue
            if not (v["available_from"] <= now <= v["available_to"]):
                continue
            travel = walking_time_s(v["lonlat"], c["lonlat"])
            if t_now + travel > c["window_end"]:
                continue                                    # FR-16: cannot arrive in time
            x[i, j] = model.NewBoolVar(f"x_{i}_{j}")

    if not x:
        return []
    for i in range(len(candidates)):
        vars_i = [x[i, j] for j in range(len(volunteers)) if (i, j) in x]
        if vars_i:
            model.AddAtMostOne(vars_i)
    for j in range(len(volunteers)):
        vars_j = [x[i, j] for i in range(len(candidates)) if (i, j) in x]
        if vars_j:
            model.AddAtMostOne(vars_j)
    model.Maximize(sum(int(candidates[i]["ec2_gain"] * 1e9) * var
                       for (i, _j), var in x.items()))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5.0
    if solver.Solve(model) not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return []
    return [(candidates[i]["candidate_id"], volunteers[j]["volunteer_id"])
            for (i, j), var in x.items() if solver.Value(var)]
