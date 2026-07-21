#!/usr/bin/env python3
"""
Generate the monster spawn-area data the map consumes.

Reads Silkroad's raw npcpos.txt (per-mob spawn coordinates) from the main
SROCodex repo, joins it to the monster roster (names/levels), and emits one
JSON file the map loads to draw each monster's spawn AREA.

Pipeline per monster:
  spawn points -> cluster nearby ones -> convex hull per cluster (the "area")
                                      -> plus the raw points (the "dots")

Coordinates are emitted already projected into the map's own lat/lng space
(the same space the map's CoordSROToMap produces), so the map draws them
directly. World layer only for now (region id <= 32767); dungeon mobs are a
follow-up (their coords live on separate map layers).

Usage:
  python tools/gen_monster_spawns.py
  python tools/gen_monster_spawns.py --npcpos <path> --monsters <path> --out <path>
"""
import argparse, json, os

# Defaults point at the sibling SROCodex repo's extracted game data.
HERE = os.path.dirname(os.path.abspath(__file__))
DEF_NPCPOS   = r"C:\VS Projects\SROCodex\Pk2 Resources\Media\server_dep\silkroad\textdata\npcpos.txt"
DEF_MONSTERS = r"C:\VS Projects\SROCodex\SROCodex\SeedData\monsters.json"
DEF_OUT      = os.path.join(HERE, "..", "assets", "data", "monster-spawns.json")

CLUSTER_DIST = 0.9   # map units: points closer than this join into one area

def region_to_latlng(region, X, Z):
    """Region-local (X, Z) in a world region -> the map's lat/lng.
    Mirrors CoordSROToMap's world branch in assets/js/xSROMap.js."""
    lat = ((region >> 8) & 0xFF) + Z / 1920.0 - 1
    lng = (region & 0xFF) + X / 1920.0
    return (round(lat, 4), round(lng, 4))

def read_spawns(path):
    """mobId -> list of (lat, lng) for world-layer spawn points."""
    spawns = {}
    with open(path, encoding="utf-16") as f:
        for line in f:
            c = line.rstrip("\n").split("\t")
            if len(c) < 5 or not c[0].lstrip("-").isdigit():
                continue
            region = int(c[1])
            if region > 32767:          # dungeon layer - skip for now
                continue
            mob = int(c[0])
            try:
                X, Z = float(c[2]), float(c[4])
            except ValueError:
                continue
            spawns.setdefault(mob, []).append(region_to_latlng(region, X, Z))
    return spawns

def cluster(points, dist):
    """Union-find: group points within `dist` of each other (single-linkage)."""
    n = len(points)
    parent = list(range(n))
    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
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

def convex_hull(pts):
    """Andrew's monotone chain. Returns [] for < 3 distinct points."""
    P = sorted(set(pts))
    if len(P) < 3:
        return []
    def cross(o, a, b):
        return (a[1]-o[1])*(b[0]-o[0]) - (a[0]-o[0])*(b[1]-o[1])
    lower = []
    for p in P:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(P):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--npcpos", default=DEF_NPCPOS)
    ap.add_argument("--monsters", default=DEF_MONSTERS)
    ap.add_argument("--out", default=DEF_OUT)
    args = ap.parse_args()

    spawns = read_spawns(args.npcpos)
    monsters = {m["id"]: m for m in json.load(open(args.monsters, encoding="utf-8-sig"))}

    out = {}
    stats = {"monsters_with_area": 0, "monsters_dots_only": 0,
             "total_points": 0, "total_clusters": 0}
    for mob, pts in spawns.items():
        m = monsters.get(mob)
        if not m:
            continue                    # spawn id isn't a roster monster (NPC/pet/etc.)
        clusters = cluster(pts, CLUSTER_DIST)
        areas = [h for h in (convex_hull(c) for c in clusters) if h]
        out[str(mob)] = {
            "name": m.get("name"),
            "minLevel": m.get("minLevel"),
            "maxLevel": m.get("maxLevel"),
            "region": m.get("region"),
            "rarity": m.get("rarity"),
            "areas": areas,
            "dots": pts,
        }
        stats["total_points"] += len(pts)
        stats["total_clusters"] += len(clusters)
        stats["monsters_with_area" if areas else "monsters_dots_only"] += 1

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"))
    size = os.path.getsize(args.out)

    print(f"monsters emitted:      {len(out)}")
    print(f"  with a drawn area:   {stats['monsters_with_area']}")
    print(f"  dots-only (<3 pts):  {stats['monsters_dots_only']}")
    print(f"spawn points:          {stats['total_points']}")
    print(f"clusters:              {stats['total_clusters']}")
    print(f"output:                {os.path.relpath(args.out)}  ({size/1024:.0f} KB)")

if __name__ == "__main__":
    main()
