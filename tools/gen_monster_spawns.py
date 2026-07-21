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

# Town centres in in-game (PosX, PosY), from the sidebar Towns list. Boxes are
# NOT hardcoded - they're derived from the data: a town is the mob-free gap, so
# the nearest spawns on each side mark its walls (see town_boxes).
TOWN_CENTERS = [
    ("Jangan", 6434, 1044), ("Donwhang", 3554, 2112), ("Hotan", 114, 47.25),
    ("Samarkand", -5184, 2889), ("Constantinople", -10681, 2584),
    ("Alexandria", -16147, 75), ("Baghdad", -8525, -717),
]

def ig_to_latlng(posX, posY):
    """In-game (PosX, PosY) -> map lat/lng. Mirrors CoordSROToMap's game branch."""
    return (posY / 192.0 + 91, posX / 192.0 + 135)

def town_boxes(mob_points):
    """For each town, find the empty box around its centre bounded by the
    nearest monster spawns on the N/S/E/W axes."""
    boxes = []
    for name, px, py in TOWN_CENTERS:
        clat, clng = ig_to_latlng(px, py)
        near_lng = [abs(p[1]-clng) for p in mob_points if abs(p[0]-clat) < 0.6 and abs(p[1]-clng) < 3]
        near_lat = [abs(p[0]-clat) for p in mob_points if abs(p[1]-clng) < 0.6 and abs(p[0]-clat) < 3]
        b = max((min(near_lng) - 0.05) if near_lng else 1.0, 0.3)   # half-width (lng)
        a = max((min(near_lat) - 0.05) if near_lat else 1.0, 0.3)   # half-height (lat)
        boxes.append({"name": name, "latMin": clat-a, "latMax": clat+a,
                      "lngMin": clng-b, "lngMax": clng+b})
    return boxes

def box_ring(box):
    return [[box["latMin"], box["lngMin"]], [box["latMin"], box["lngMax"]],
            [box["latMax"], box["lngMax"]], [box["latMax"], box["lngMin"]]]

def box_bbox(box):
    return (box["latMin"], box["lngMin"], box["latMax"], box["lngMax"])

def hull_bbox(hull):
    lats = [p[0] for p in hull]; lngs = [p[1] for p in hull]
    return (min(lats), min(lngs), max(lats), max(lngs))

def bb_overlap(a, b):
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])

def clip_to_hull(subject, hull):
    """Sutherland-Hodgman clip of a polygon against the (convex) hull. Returns
    the intersection - always inside the hull, so it renders as a clean evenodd
    hole whether the town sits fully inside the area or straddles its edge.
    Points are (lat, lng); geometry treats x=lng, y=lat."""
    def sarea(poly):
        return sum(poly[i][1]*poly[(i+1)%len(poly)][0] - poly[(i+1)%len(poly)][1]*poly[i][0]
                   for i in range(len(poly))) / 2.0
    H = hull if sarea(hull) > 0 else hull[::-1]     # want CCW so interior is on the left
    def side(p, a, b):
        return (b[1]-a[1])*(p[0]-a[0]) - (b[0]-a[0])*(p[1]-a[1])
    out = subject[:]
    for i in range(len(H)):
        a, b = H[i], H[(i+1) % len(H)]
        inp, out = out, []
        if not inp:
            break
        for j in range(len(inp)):
            cur, prev = inp[j], inp[j-1]
            cs, ps = side(cur, a, b), side(prev, a, b)
            def inter():
                t = ps / (ps - cs) if ps != cs else 0.0
                return [prev[0]+t*(cur[0]-prev[0]), prev[1]+t*(cur[1]-prev[1])]
            if cs >= 0:
                if ps < 0:
                    out.append(inter())
                out.append(cur)
            elif ps >= 0:
                out.append(inter())
    return [[round(p[0], 4), round(p[1], 4)] for p in out]

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

    # Derive town boxes from every monster's spawn points (the mob-free gaps).
    all_mob_pts = [p for mob, pts in spawns.items() if mob in monsters for p in pts]
    towns = town_boxes(all_mob_pts)

    out = {}
    stats = {"monsters_with_area": 0, "monsters_dots_only": 0,
             "total_points": 0, "total_clusters": 0, "holes_punched": 0}
    for mob, pts in spawns.items():
        m = monsters.get(mob)
        if not m:
            continue                    # spawn id isn't a roster monster (NPC/pet/etc.)
        clusters = cluster(pts, CLUSTER_DIST)
        areas = []
        for c in clusters:
            hull = convex_hull(c)
            if not hull:
                continue
            hb = hull_bbox(hull)
            holes = []
            for t in towns:
                if not bb_overlap(box_bbox(t), hb):
                    continue
                clipped = clip_to_hull(box_ring(t), hull)
                if len(clipped) >= 3:
                    holes.append(clipped)
            stats["holes_punched"] += len(holes)
            areas.append({"outer": hull, "holes": holes})
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
    print(f"town holes punched:    {stats['holes_punched']}")
    print("town boxes (lat/lng):")
    for t in towns:
        print(f"  {t['name']:<16} lat[{t['latMin']:.2f},{t['latMax']:.2f}] lng[{t['lngMin']:.2f},{t['lngMax']:.2f}]")
    print(f"output:                {os.path.relpath(args.out)}  ({size/1024:.0f} KB)")

if __name__ == "__main__":
    main()
