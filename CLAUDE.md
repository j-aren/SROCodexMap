# CLAUDE.md — SROCodexMap

## What this repo is

SROCodexMap is the **interactive world map** for SROCodex (srocodex.org). It's a
fork of **[JellyBitz/xSROMap](https://github.com/JellyBitz/xSROMap)** (MIT), a
static Leaflet-based Silkroad Online map. It's hosted on **GitHub Pages**
(`j-aren.github.io/SROCodexMap`) and **iframed** into the main site's `/maps`
page.

Why a fork instead of vendoring the map into the main site: the tile set is
~290–390MB. Forking keeps that weight out of SROCodex's repo and Docker image,
lets us restyle freely, and means we don't depend on JellyBitz's site staying up.

**Relationship to the main project:** SROCodex is a separate ASP.NET Core repo
at `C:\VS Projects\SROCodex` (its own CLAUDE.md, its own Render deploy). This
repo is *just the map*. Keep the two mental models separate. The main site
consumes this only through the iframe `src` and, later, through deep-link URLs
(see "Show on map" below).

## The working agreement (same as the main project)

This is **Javi's learning project**; the primary output is his understanding,
the working map is the byproduct. Same rules as SROCodex:

1. **Concepts before code.** Explain what/why/where-it-fits before implementing
   anything non-trivial. 1–2 steps at a time.
2. **Javi writes the interesting parts** — the JS logic (map API usage,
   coordinate handling, the deep-link feature, data wiring). Walk him through it,
   have him predict what code does, let him write or meaningfully modify it.
3. **Claude writes the boring parts** — CSS restyling, HTML markup, repetitive
   sidebar entries. Generate with a short summary.
4. **The line:** if getting it wrong teaches him something, he writes it. If it's
   a typo hunt, generate it. Unsure? Ask.
5. **Errors are teaching moments** — have him read the error and guess the cause
   before fixing.

Cross-cutting preferences carried from the main project:
- **Security is a standing priority** — teach it alongside the work.
- **No AI-looking commits** — no "Co-Authored-By: Claude" trailer; write commit
  messages like a human, saying *why* not just *what*.
- **Defer to Javi's game knowledge** over naming/ordering/data defaults — he's
  played since 2005 and knows the world map cold (region order, zone names).

## License & credit — non-negotiable

The upstream is **MIT © 2019 Engels Quintero (JellyBitz)**. No matter how much we
restyle or rebrand:
- **Keep the `LICENSE` file** intact.
- **Keep a visible credit to JellyBitz** somewhere in the UI (the sidebar
  currently carries it). When we rebrand the sidebar to SROCodex, the JellyBitz
  MIT credit must survive — move it, restyle it, but don't delete it.
- The main site also credits "Map by JellyBitz" on `/maps` and in its footer.

## Stack & structure

Plain static site — no build step. Open it and it runs.

- `index.html` — the whole page. Sidebar (brand, search, Towns/Zones/Areas/NPCs
  navigation, script-editor modal) + a `#map` div. Loads everything via
  `<link>`/`<script>`.
- `assets/css/main.css` — **the main restyle surface** (~12KB). The theme is
  keyed off the `jelly-theme` body class and `jelly-color` accent class.
- `assets/js/xSROMap.js` — the **map API** (the reusable library). Its public
  methods are documented in `README.md`'s method table. This is the important
  file to understand for features.
- `assets/js/main.js` — app wiring: initializes the map, populates NPC lists,
  hooks up search and the script editor.
- `assets/js/leaflet/` — Leaflet + plugins (Geoman = drawing, EasyButton).
  Third-party; don't rewrite, just use.
- `assets/img/silkroad/` — **the ~388MB tile set** (the actual map imagery,
  served as Leaflet tiles). Touch only for the "replace tiles/art" work stream.
- `assets/fonts/font-awesome-5.11.1/` — icons (local, 15MB).

- `assets/js/vendor/`, `assets/css/vendor/` — jQuery 3.7.1, Popper 1.16.1,
  Bootstrap 4.6.2, vendored locally. **Keep them local.** Upstream loaded these
  from CDNs, which would be defensible for a standalone site — but this page is
  iframed into srocodex.org, so a third-party script origin here is a
  third-party script origin on our domain. (Upstream's jQuery tag also carried
  no SRI hash at all.) Don't reintroduce a CDN tag for convenience. `.gitattributes`
  keeps these byte-identical to what upstream published so they stay checksum-verifiable.
  Bootstrap stays on **4.x** — 5.x drops jQuery and would break the sidebar and modal markup.

**No analytics.** Upstream shipped JellyBitz's Google Analytics tag; it was
removed. If we ever want analytics, it goes through whatever the main site uses,
not a second tag inside the iframe.

## Coordinate systems (read before any map-position work)

The map speaks two coordinate types (see README):
- **IG** — in-game coords: `PosX, PosY`. What players see (e.g. `/6434,1044` for
  Jangan).
- **IC** — internal client coords: `X, Y, Z, Region`. What the pk2 data files
  store. `npcpos.txt` gives NPC/mob positions as `x, z, y, region`.

Every positioning method has both overloads: `SetView`/`FlyView`/`AddNPC` etc.
This directly answers the open question in the main project's roadmap ("how to
convert region-local coords to the map's system") — **you don't convert; you pass
the IC overload the raw `x, z, y, region` from npcpos.** Mind the axis order:
npcpos is `x, z, y, region`, and the IC overloads take `X, Y, Z, Region` — so map
npcpos `z`→Y and npcpos `y`→Z when calling. Verify against a known NPC before
trusting it wholesale.

## The work streams (what Javi wants to change)

Three directions, roughly increasing in effort:

1. **Restyle the UI** — retheme from JellyBitz's dark "jelly" look to SROCodex's
   **desert-codex** palette (below). Sidebar, search, buttons, map controls,
   marker popups. Pure front-end (`main.css` + sidebar markup in `index.html`).
   Rebrand text to SROCodex — *keeping the JellyBitz MIT credit*. Lowest risk,
   highest visible payoff. Good first slice.
2. **New features / behavior** — search improvements, custom markers, layer
   toggles, and the flagship: **"Show on map" deep-links.** The main site's
   quest/monster pages link to this map with coords so it opens centered on the
   giver NPC / mob spawn. Mechanism already exists: the map **accepts GET params**
   for shareable location links (README), and `main.js` reads them. So the main
   site just builds a URL; this repo makes sure the param handling + `FlyView`/
   marker highlight land where we want. Design the URL contract deliberately.

   **Security note for this work stream:** URL params are attacker-controlled
   input, and both `main.js` and `xSROMap.js` build popup/sidebar HTML by string
   concatenation before handing it to jQuery/Leaflet. Anything off the query
   string must be validated (coords → `parseFloat` + finite/range check, never
   interpolated raw) or escaped before it reaches an HTML sink. Note the param
   readers already exist in **two** places — `xSROMap.js:273` positions the map,
   `main.js:153` prefills the search box — so validation has to cover both, or
   they should be consolidated into one reader.
3. **Replace the tiles / art** — swap or re-render the actual map imagery under
   `assets/img/silkroad/`. Heavy, involved, and it's what makes the clone large.
   Save for last; understand the tile naming/zoom-level scheme first.

## Design reference (match the main site)

Dark desert-codex theme, same palette as SROCodex so the iframe feels native:

- Page/panel bg near-black warm brown `#171310`; raised surfaces `#211a14`;
  hairline borders `#3a3226`.
- Primary text warm parchment `#e8dcc3`; secondary `#9c8b6d`.
- Accent gold `#d9b25f` — **scarce**: active/selected nav, the brand, key
  highlights. Not everywhere.
- Serif (Georgia stack) only for the brand/wordmark; clean sans for everything
  functional.
- SROCodex's logo mark (a camel crossing the dunes) can front the sidebar brand —
  the SVG lives in the main repo at `SROCodex/wwwroot/img/discord-icon.svg` /
  `Pages/Shared/_LogoMark.cshtml` if we want to reuse it.

## Local development

No build. Two ways to run:
- Quickest: open `index.html` in a browser.
- Better (matches how GitHub Pages serves it, avoids any file:// AJAX issues):
  run a static server from the repo root and hit `http://localhost:8000` —
  e.g. `python -m http.server 8000`.

## Deploy

**GitHub Pages.** Pushing to the branch Pages is configured to serve publishes
the live map at `j-aren.github.io/SROCodexMap`, which the main site iframes.
Confirm which branch Pages uses (repo Settings → Pages) before pushing — a push
to the served branch is a live deploy, so branch deliberately and preview locally
first. No secrets, no env vars, no server.

## Conventions

- Commit early and often; messages say *why*, not just *what*. No AI-looking
  commits.
- Keep the JellyBitz MIT credit visible; keep `LICENSE`.
- Restyle by editing `main.css` and swapping the `jelly-theme`/`jelly-color`
  hooks toward the desert palette — prefer retheming the existing classes over
  ripping out the structure, so upstream changes stay mergeable if ever needed.
- Don't rewrite Leaflet or its plugins; use their APIs.
