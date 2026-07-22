#!/usr/bin/env python3
"""
Generate the monster spawn-area data the map consumes.

Reads Silkroad's raw npcpos.txt (per-mob spawn coordinates) from the main
SROCodex repo, joins it to the monster roster (names/levels), and emits one
JSON file the map loads to draw each monster's spawn AREA.

Pipeline per monster:
  spawn points -> cluster nearby ones (a mob can spawn in several places)
               -> per cluster: buffer the points and trace the union outline
                  (marching squares over a distance field) -> a concave "area"
                  that follows the outer spawns and flows around gaps (towns)
               -> simplify each outline (Douglas-Peucker)

The buffer is the roaming allowance; towns (no spawns) survive as gaps as long
as the buffer is smaller than the town is wide - so towns are excluded for free,
no town list needed.

Coordinates are emitted already projected into the map's own lat/lng space, so
the map draws them directly. World layer only for now (region id <= 32767).

Usage:
  python tools/gen_monster_spawns.py
"""
import argparse, json, os, math

HERE = os.path.dirname(os.path.abspath(__file__))
DEF_NPCPOS   = r"C:\VS Projects\SROCodex\Pk2 Resources\Media\server_dep\silkroad\textdata\npcpos.txt"
DEF_MONSTERS = r"C:\VS Projects\SROCodex\SROCodex\SeedData\monsters.json"
DEF_OUT      = os.path.join(HERE, "..", "assets", "data", "monster-spawns.json")

CLUSTER_DIST = 0.9    # map units: points closer than this join into one cluster
BUFFER       = 0.45   # roaming radius around each spawn (map units)
CELL         = 0.08   # marching-squares grid resolution
SIMPLIFY     = 0.05   # Douglas-Peucker tolerance for the traced outline

# Regular mobs get a colour per zone (distinct within a zone; a colour may repeat
# in another zone). Uniques are all one colour. Used when several mobs are shown
# at once (all / uniques / a whole zone).
PALETTE = ["#e0662f", "#3d8ad6", "#e8c53a", "#2fb38a", "#d63d7a",
           "#8ad63d", "#d64545", "#3dd6d6", "#e89a3a", "#5a9e5a"]
UNIQUE_COLOR = "#a94fd6"

def assign_colors(out, monsters):
    """Colour each mob: uniques purple, regulars cycling a palette per zone."""
    per_zone = {}
    for mob_id in sorted(out, key=lambda k: (out[k].get("region") or "~", int(k))):
        m = out[mob_id]
        if m.get("rarity") == "Unique":
            m["color"] = UNIQUE_COLOR
        else:
            zone = m.get("region") or "_none"
            i = per_zone.get(zone, 0)
            m["color"] = PALETTE[i % len(PALETTE)]
            per_zone[zone] = i + 1

def region_to_latlng(region, X, Z):
    """Region-local (X, Z) in a world region -> the map's lat/lng."""
    return (round(((region >> 8) & 0xFF) + Z / 1920.0 - 1, 4),
            round((region & 0xFF) + X / 1920.0, 4))

def read_spawns(path):
    spawns = {}
    with open(path, encoding="utf-16") as f:
        for line in f:
            c = line.rstrip("\n").split("\t")
            if len(c) < 5 or not c[0].lstrip("-").isdigit():
                continue
            region = int(c[1])
            if region > 32767:
                continue
            try:
                X, Z = float(c[2]), float(c[4])
            except ValueError:
                continue
            spawns.setdefault(int(c[0]), []).append(region_to_latlng(region, X, Z))
    return spawns

def cluster(points, dist):
    n = len(points); parent = list(range(n))
    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]; a = parent[a]
        return a
    d2 = dist * dist
    for i in range(n):
        for j in range(i + 1, n):
            if (points[i][0]-points[j][0])**2 + (points[i][1]-points[j][1])**2 < d2:
                parent[find(i)] = find(j)
    groups = {}
    for i, p in enumerate(points):
        groups.setdefault(find(i), []).append(p)
    return list(groups.values())

# Marching-squares segment table, corner bits: BL=1, BR=2, TR=4, TL=8
_SEG = {0:[],1:[('L','B')],2:[('B','R')],3:[('L','R')],4:[('R','T')],
        5:[('L','B'),('R','T')],6:[('B','T')],7:[('L','T')],8:[('T','L')],
        9:[('T','B')],10:[('L','T'),('B','R')],11:[('T','R')],12:[('R','L')],
        13:[('R','B')],14:[('L','B')],15:[]}

def trace_area(points, R, cell):
    """Buffer the points by R, trace the union outline. Returns a list of rings
    (an outer ring per blob, plus interior rings for enclosed gaps like towns)."""
    lat0 = min(p[0] for p in points) - R - cell; lat1 = max(p[0] for p in points) + R + cell
    lng0 = min(p[1] for p in points) - R - cell; lng1 = max(p[1] for p in points) + R + cell
    nI = int((lat1 - lat0) / cell) + 2; nJ = int((lng1 - lng0) / cell) + 2
    def dist(la, ln):
        m = 1e18
        for pa, pn in points:
            d = (la-pa)**2 + (ln-pn)**2
            if d < m: m = d
        return math.sqrt(m)
    F = [[dist(lat0 + i*cell, lng0 + j*cell) for j in range(nJ)] for i in range(nI)]
    def crossing(edge, i, j):
        def pt(a, b, va, vb):
            t = (R - va) / (vb - va) if vb != va else 0.5
            return (round(a[0] + t*(b[0]-a[0]), 4), round(a[1] + t*(b[1]-a[1]), 4))
        BL = (lat0 + i*cell, lng0 + j*cell);       BR = (lat0 + i*cell, lng0 + (j+1)*cell)
        TR = (lat0 + (i+1)*cell, lng0 + (j+1)*cell); TL = (lat0 + (i+1)*cell, lng0 + j*cell)
        if edge == 'B': return pt(BL, BR, F[i][j], F[i][j+1])
        if edge == 'R': return pt(BR, TR, F[i][j+1], F[i+1][j+1])
        if edge == 'T': return pt(TL, TR, F[i+1][j], F[i+1][j+1])
        if edge == 'L': return pt(BL, TL, F[i][j], F[i+1][j])
    segs = []
    for i in range(nI - 1):
        for j in range(nJ - 1):
            c = ((1 if F[i][j]   < R else 0) | (2 if F[i][j+1]   < R else 0) |
                 (4 if F[i+1][j+1] < R else 0) | (8 if F[i+1][j] < R else 0))
            for e1, e2 in _SEG[c]:
                segs.append((crossing(e1, i, j), crossing(e2, i, j)))
    # chain segments into closed rings
    from collections import defaultdict
    adj = defaultdict(list)
    for a, b in segs:
        adj[a].append(b); adj[b].append(a)
    def key(a, b): return (a, b) if a <= b else (b, a)
    used = set(); rings = []
    for a, b in segs:
        if key(a, b) in used: continue
        ring = [a]; cur = b; used.add(key(a, b))
        while cur != ring[0]:
            ring.append(cur)
            nxt = next((n for n in adj[cur] if key(cur, n) not in used), None)
            if nxt is None: break
            used.add(key(cur, nxt)); cur = nxt
        if len(ring) >= 4: rings.append(ring)
    return rings

def rdp(pts, eps):
    """Douglas-Peucker on an open polyline."""
    if len(pts) < 3: return pts
    a, b = pts[0], pts[-1]
    dx, dy = b[0]-a[0], b[1]-a[1]
    nrm = math.hypot(dx, dy) or 1e-12
    dmax, idx = 0.0, 0
    for i in range(1, len(pts)-1):
        d = abs((pts[i][0]-a[0])*dy - (pts[i][1]-a[1])*dx) / nrm
        if d > dmax: dmax, idx = d, i
    if dmax > eps:
        return rdp(pts[:idx+1], eps)[:-1] + rdp(pts[idx:], eps)
    return [a, b]

def simplify_ring(ring, eps):
    # simplify as an open polyline; closing it first makes the RDP base line
    # degenerate (start == end) and collapses the whole ring
    s = rdp(ring, eps)
    return [[round(p[0], 4), round(p[1], 4)] for p in s]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--npcpos", default=DEF_NPCPOS)
    ap.add_argument("--monsters", default=DEF_MONSTERS)
    ap.add_argument("--out", default=DEF_OUT)
    args = ap.parse_args()

    spawns = read_spawns(args.npcpos)
    monsters = {m["id"]: m for m in json.load(open(args.monsters, encoding="utf-8-sig"))}

    out = {}
    stats = {"total_points": 0, "total_areas": 0, "total_vertices": 0}
    for mob, pts in spawns.items():
        m = monsters.get(mob)
        if not m:
            continue
        rings = []
        for c in cluster(pts, CLUSTER_DIST):
            for ring in trace_area(c, BUFFER, CELL):
                sr = simplify_ring(ring, SIMPLIFY)
                if len(sr) >= 3:
                    rings.append(sr)
        out[str(mob)] = {
            "name": m.get("name"), "minLevel": m.get("minLevel"),
            "maxLevel": m.get("maxLevel"), "region": m.get("region"),
            "rarity": m.get("rarity"), "areas": rings, "dots": pts,
        }
        stats["total_points"] += len(pts)
        stats["total_areas"] += len(rings)
        stats["total_vertices"] += sum(len(r) for r in rings)

    assign_colors(out, monsters)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"))
    size = os.path.getsize(args.out)
    print(f"monsters emitted:  {len(out)}")
    print(f"spawn points:      {stats['total_points']}")
    print(f"areas (rings):     {stats['total_areas']}")
    print(f"avg vertices/ring: {stats['total_vertices']/max(stats['total_areas'],1):.1f}")
    print(f"output:            {os.path.relpath(args.out)}  ({size/1024:.0f} KB)")

if __name__ == "__main__":
    main()
