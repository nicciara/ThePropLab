# ARCHITECTURAL REVIEW & IMPLEMENTATION PLAN
## Interactive Strike Zone Analysis Grid Feature
**Created**: June 18, 2026 | **Status**: Pre-Implementation Analysis  
**Feature Complexity**: HIGH | **Estimated Effort**: 40-60 dev hours (MVP to advanced)

---

## EXECUTIVE SUMMARY

The Interactive Strike Zone Analysis Grid is a **transformational feature** that elevates The Prop Lab from a basic stats dashboard to a **advanced pitch analysis platform**. This document provides a senior architect's review of your current codebase and a detailed roadmap for implementation.

### Key Findings
✅ **Good**: Your architecture is clean, well-organized, and uses proven patterns (session state, caching, API abstraction)  
⚠️ **Concerns**: Single-file app will become unmaintainable; Baseball Savant scraping fragility; HTML/CSS inline styling needs refactoring  
🎯 **Opportunity**: This feature is the natural next step—will unlock batter views, advanced filters, and comparison tools

---

## PART 1: CODEBASE ANALYSIS

### 1.1 Current Architecture Overview

```
ARCHITECTURE: Single-Page Streamlit App
├── Data Layer
│   ├── MLB Stats API (schedule, stats, lineups, player info)
│   ├── Baseball Savant (pitch arsenal scraping from HTML)
│   └── Caching (120-180s TTL via @st.cache_data)
├── Business Logic Layer
│   ├── Pitcher detail page (session state based)
│   ├── Slate view (game schedule grid)
│   └── Helper functions (formatting, normalization)
└── Presentation Layer
    ├── Inline HTML/CSS (cards, grids, status badges)
    ├── Streamlit components (columns, buttons, containers)
    └── 2-column game card grid layout
```

**Lines of Code**: ~1,000 LOC (all in app.py)  
**Modules**: 0 (everything in single file)  
**Complexity**: Medium-High (fragile due to Savant scraping, mixing concerns)

### 1.2 Strengths

| Aspect | Rating | Notes |
|--------|--------|-------|
| **Code Organization** | 🟢 Excellent | Clear separation of API calls, business logic, and rendering |
| **Caching Strategy** | 🟢 Good | Appropriate TTLs (120s for schedule, 180s for stats) |
| **Error Handling** | 🟡 Fair | Try-catches in place, but limited fallbacks; logging good |
| **Session State Management** | 🟢 Good | Clean session state pattern for pitcher navigation |
| **Data Flow** | 🟢 Good | Unidirectional, clear dependencies |
| **API Abstraction** | 🟢 Good | API calls isolated in functions with clear contracts |
| **Styling/Theming** | 🟡 Poor | Inline HTML/CSS throughout (hard to maintain) |

### 1.3 Weaknesses & Technical Debt

| Issue | Severity | Impact | Effort to Fix |
|-------|----------|--------|----------------|
| **Baseball Savant HTML Scraping** | 🔴 CRITICAL | Feature breaks if Savant changes page structure | 20-30 hrs |
| **Single File (~1000 LOC)** | 🔴 HIGH | Becoming unmaintainable; difficult to add features | 10-15 hrs refactor |
| **Inline CSS/HTML Styling** | 🟠 MEDIUM | Hard to maintain consistent theme; code duplication | 5-8 hrs cleanup |
| **No Component System** | 🟠 MEDIUM | Cards and grids hard-coded; can't reuse (strike zone will be first victim) | 8-12 hrs |
| **Limited Error Handling** | 🟠 MEDIUM | Network failures log but don't gracefully degrade UI | 5-8 hrs |
| **No Type Hints** | 🟠 MEDIUM | Harder to debug and maintain | 3-5 hrs |
| **Repeated API Logic** | 🟡 LOW | `get_players_info()` could batch more efficiently | 2-3 hrs |
| **No Configuration File** | 🟡 LOW | Hardcoded values (colors, TTLs, team logos URL) | 1-2 hrs |

### 1.4 Current Data Flow Diagram

```
User opens app.py
    ↓
[Header & Sport Selector]
    ↓
load_schedule(date)
    ├─ MLB Stats API → games, pitchers, teams
    ├─ get_players_info() → pitcher handedness
    └─ Returns: DataFrame(game_pk, away_pitcher, home_pitcher, status, etc.)
    ↓
[Slate View] ← 2-column game grid
    ├─ Per game: load_lineups(game_pk)
    │   ├─ MLB Stats API.1.1/game/{game_pk}/feed/live
    │   └─ Returns: [away_lineup], [home_lineup]
    ├─ Pitcher click → set session state
    └─ Render game cards with pitcher buttons
    ↓
[Pitcher Detail Page] ← session-state triggered
    ├─ load_pitcher_stats(player_id)
    │   └─ MLB Stats API → ERA, WHIP, K%, BB%, IP, HR
    ├─ get_savant_arsenal_for_player(player_id)
    │   ├─ Baseball Savant HTML scrape → /savant-player/{player_id}
    │   ├─ JSON extraction from embedded HTML
    │   └─ Returns: pitch types, velocities, counts
    ├─ [Display cards]
    │   ├─ 2026 Season stats
    │   ├─ Pitch Arsenal breakdown
    │   ├─ Matchup Context
    │   ├─ Matchup Read
    │   └─ Opposing Lineup
    └─ Back to Slate
```

---

## PART 2: WHERE THE STRIKE ZONE FEATURE LIVES

### 2.1 Feature Location

**Primary Home**: Pitcher Detail Page (`/pitcher/{player_id}` conceptually)  
**Placement**: After "Matchup Read" section, before "Opposing Lineup" (or in tabs)  
**Future Homes**: Batter detail page, comparison view, historical charts

```
Pitcher Detail Page Structure (Proposed)
┌─────────────────────────────────────────────┐
│ ← Back to Slate                             │
│ Pitcher Name (Hand)                         │
│ Team | Opponent | Game Info | Venue        │
└─────────────────────────────────────────────┘

┌─ Tabs or Sections ──────────────────────────┐
│ [Overview] [Strike Zone] [Splits] [Trends]  │
└─────────────────────────────────────────────┘

[Overview Tab - Current]
  ├─ Pitcher Stats (3-col grid)
  ├─ Pitch Arsenal
  ├─ Matchup Context
  ├─ Matchup Read
  └─ Opposing Lineup

[Strike Zone Tab - NEW]
  ├─ Visualization Controls
  │   ├─ Metric dropdown: Pitch %, Total Pitches, Batted Balls, Hits, HR, Barrel%, SLG, xSLG, AVG, xBA, wOBA, xwOBA
  │   ├─ Pitch Type dropdown: All, 4-Seam, Slider, Cutter, Changeup, etc. (dynamic from arsenal)
  │   └─ Optional: Handedness filter (vs RHB/LHB), Date range
  ├─ Strike Zone Grid
  │   ├─ 9-12 zone grid (overlaid on strike zone visual)
  │   ├─ Each cell shows: metric value + percentage
  │   ├─ Color intensity = metric value (heatmap style)
  │   └─ Hover tooltip: detailed stats for zone
  └─ Alternative View: MLB Savant-style visualization

[Splits Tab - Future]
  ├─ Vs RHB / Vs LHB splits
  ├─ Recent form, trends

[Trends Tab - Future]
  ├─ Season progression chart
  ├─ Recent starts
```

### 2.2 Integration Points

**Touch Points in Current Code**:
1. **Pitcher Detail Page** (~line 420-620): Add new tab or section
2. **Session State**: Extend with `selected_tab`, `selected_metric`, `selected_pitch_type`
3. **Data Fetching**: New function `get_savant_pitch_location_data(player_id, pitch_type)` or equivalent
4. **Visualization**: New component (or Plotly/Altair chart)

**No changes needed**:
- Schedule loading
- Lineup fetching
- Caching logic (will reuse same pattern)
- Session state navigation (back button still works)

---

## PART 3: FILES THAT NEED MODIFICATION

### 3.1 Critical Files

| File | Changes | Priority | Complexity |
|------|---------|----------|------------|
| **app.py** | Add strike zone section, data fetching, rendering | 🔴 MUST | HIGH |
| **NEW: strike_zone.py** | Strike zone visualization component | 🔴 MUST | HIGH |
| **NEW: data_layer.py** | Extract Savant pitch location fetching | 🟠 SHOULD | MEDIUM |

### 3.2 Refactoring (Recommended Before Strike Zone)

| File | Changes | Priority | Effort | Blocks Strike Zone? |
|------|---------|----------|--------|---------------------|
| **NEW: components.py** | Extract stat cards, pitch arsenal, lineup display | 🟠 SHOULD | 8 hrs | No, but reduces complexity |
| **NEW: config.py** | Extract hardcoded values (colors, team logo URL, TTLs) | 🟡 NICE | 2 hrs | No |
| **NEW: styles.py** | Centralize inline CSS/HTML templates | 🟡 NICE | 5 hrs | No, but cleaner |
| **app.py** | Add type hints to functions | 🟡 NICE | 3 hrs | No |

### 3.3 Future Files (For Advanced Version)

| File | Purpose | When |
|------|---------|------|
| **NEW: database.py** | Local SQLite cache for pitch location data | Phase 2 (if Savant unreliable) |
| **NEW: batter_view.py** | Batter detail page logic | Phase 3 |
| **NEW: comparison.py** | Multi-pitcher comparison view | Phase 4 |

---

## PART 4: TECHNICAL DEBT TO ADDRESS FIRST

### 4.1 Critical Blocker: Baseball Savant Scraping

**Current Issue**:  
The app relies on HTML scraping of Baseball Savant (`/savant-player/{player_id}`) to get pitch arsenal. This is **fragile**—if Savant changes page structure, the entire pitch arsenal feature breaks.

**For Strike Zone Feature**, we need **pitch location data** (x, y coordinates in strike zone). This data:
- ✅ IS available on Baseball Savant player pages (in StatCast visualization)
- ❌ Is NOT available via official MLB Stats API
- ❌ Requires scraping or reverse-engineering Savant's API calls

**Options**:

| Option | Pros | Cons | Recommendation |
|--------|------|------|-----------------|
| **Continue Scraping Savant** | Works today; no API key needed | Fragile; breaks frequently; slow (~2s per player) | ⚠️ For MVP only |
| **Reverse-Engineer Savant's API** | More robust than HTML parsing | Time-consuming; requires reverse-eng skills; may violate ToS | ⚠️ Medium-term |
| **Use Unofficial Statcast DB** | pybaseball or similar packages | Limited control; may be out of sync | ✅ For MVP (backup) |
| **Partner with Savant/Trackman** | Official support; guaranteed stability | Requires licensing; cost | ✅ Long-term production |

**Recommended Approach for MVP**:
1. Use `pybaseball` package to fetch Statcast data (pitch locations)
2. Fall back to MLB Stats API if Savant unavailable
3. Cache locally to minimize API calls
4. Plan for official partnership in Phase 2

---

### 4.2 Secondary Debt: Code Organization

**Current**: 1000 LOC in single app.py  
**Problem**: Hard to add new features; difficult to test; mixing concerns

**For Strike Zone Implementation**:
- Extract `strike_zone_data.py` for pitch location fetching
- Extract `strike_zone_viz.py` for visualization component
- Extract `components.py` for reusable stat cards, grids, etc.

**Minimal Refactoring Before Strike Zone** (8-10 hours):
1. Create `data_layer.py` - centralize all API fetching and caching
2. Create `components.py` - extract stat card rendering
3. Create `strike_zone.py` - new strike zone component
4. Leave `app.py` as main orchestrator

---

## PART 5: DATA FLOW DESIGN (STRIKE ZONE)

### 5.1 Data Requirements

**What We Need**:
- Pitcher ID
- Pitch type (optional; if provided, filter to that type)
- Batter handedness (vs RHB/LHB filter)
- Metric type (Pitch %, Total Pitches, Hits, HR, SLG, wOBA, xwOBA, etc.)
- Date range (optional; defaults to full season)

**What We're Fetching**:
- Pitch locations (x, y coordinates in strike zone)
- Pitch types (4-seam, slider, changeup, etc.)
- Outcomes (ball, strike, hit, home run, barrel, etc.)
- Exit velocity, launch angle, barrel/BIP classification
- Base hits, home runs, slugging %, wOBA

**Source Options**:

| Source | Data Available | Ease | Speed | Recommended |
|--------|-----------------|------|-------|-------------|
| **MLB Stats API** | Pitch-by-pitch event data | 🟡 Moderate | Fast | ⚠️ Limited location data |
| **Baseball Savant** | Complete Statcast data (official) | 🟡 HTML scrape | Slow (2-3s) | ⚠️ For MVP |
| **pybaseball** | Statcast data (processed) | 🟢 Easy | Fast | ✅ **RECOMMENDED** |
| **Direct Statcast DB** | Raw Statcast data | 🔴 Difficult | Varies | Later phase |
| **Trackman API** | Proprietary data | 🔴 Requires license | Varies | Production-only |

### 5.2 Data Flow (MVP Architecture)

```
User selects pitcher → Click on pitcher name in slate
    ↓
load_schedule() + load_pitcher_stats() [EXISTING]
    ↓
[NEW] load_strike_zone_data(player_id, pitch_type, handedness)
    ├─ Check cache (@st.cache_data, ttl=300)
    ├─ Fetch Statcast data via pybaseball.statcast() or Savant HTML
    ├─ Filter by pitcher_id, pitch_type (if provided), batter handedness
    ├─ Aggregate into 9-12 zone grid:
    │   ├─ x-coordinate (horizontal): -2.5 to 2.5 feet
    │   ├─ y-coordinate (vertical): 1.0 to 4.5 feet
    │   ├─ Calculate metric per zone (Pitch %, Hits, HR, SLG, wOBA, etc.)
    │   └─ Return DataFrame: zone_id, metric_name, metric_value, pitch_count, hit_count, etc.
    └─ Cache result (300s TTL)
    ↓
render_strike_zone_grid(zone_data, metric_type)
    ├─ Create heatmap-style visualization
    ├─ Color intensity based on metric_value
    ├─ Overlay zone grid on strike zone visual
    ├─ Add hover tooltips with detailed stats
    └─ Display legend with color scale
```

### 5.3 Data Structure

**Input**:
```python
{
    "player_id": 123456,
    "pitch_type": "4-seam fastball",  # or None for "All"
    "vs_handedness": None,  # or "R", "L"
    "date_range": ("2026-03-28", "2026-06-18"),
    "metric": "Pitch %"  # or "Total Pitches", "Hits", "HR", "SLG", "xwOBA", etc.
}
```

**Output (Zone Aggregation)**:
```python
DataFrame(
    zone_id=[1, 2, 3, ..., 9],  # or 12 zones
    zone_label=["Top-Left", "Top-Center", ..., "Bottom-Right"],
    x_min=[-2.5, -0.8, 0.8, ...],
    x_max=[-0.8, 0.8, 2.5, ...],
    y_min=[3.5, 3.5, 3.5, ...],
    y_max=[4.5, 4.5, 4.5, ...],
    
    # Metrics (same columns repeated for each metric type)
    pitch_count=[45, 38, 52, ...],
    hit_count=[12, 11, 18, ...],
    hr_count=[2, 1, 3, ...],
    whiff_count=[15, 10, 12, ...],
    swinging_strike_count=[8, 6, 7, ...],
    
    # Calculated percentages
    pitch_pct=[5.1, 4.3, 5.9, ...],
    hit_pct=[26.7, 28.9, 34.6, ...],
    slugging=[0.456, 0.421, 0.523, ...],
    woba=[0.378, 0.401, 0.425, ...],
    xwoba=[0.372, 0.398, 0.420, ...],
)
```

### 5.4 Zone Grid Definition

**Option A: 9-Zone Grid** (Baseball Savant style; used by Statcast)
```
    HIGH
     1 2 3
     4 5 6  (5 = center/strike zone)
     7 8 9
    LOW

    OUTSIDE   STRIKE ZONE   INSIDE
      (R)      (center)       (L)

Zone coordinates (in feet, from pitcher view):
  1: x=-2.5 to -0.8, y=3.5-4.5
  2: x=-0.8 to +0.8, y=3.5-4.5
  3: x=+0.8 to +2.5, y=3.5-4.5
  4: x=-2.5 to -0.8, y=2.2-3.5
  5: x=-0.8 to +0.8, y=2.2-3.5  (pure strike zone)
  6: x=+0.8 to +2.5, y=2.2-3.5
  7: x=-2.5 to -0.8, y=1.0-2.2
  8: x=-0.8 to +0.8, y=1.0-2.2
  9: x=+0.8 to +2.5, y=1.0-2.2
```

**Option B: 12-Zone Grid** (More granular; could support MLB Savant's format)
```
Add subdivisions for better precision (e.g., high-inside vs high-center-inside)
```

**Recommendation**: Start with 9-zone grid (MVP). Expand to 12-zone in Phase 2.

---

## PART 6: VISUALIZATION APPROACH FOR STREAMLIT

### 6.1 Current Visualization Landscape

**Current App**: Uses inline HTML/CSS with Streamlit markdown  
**Limitations**: 
- No interactivity (hover tooltips, zoom)
- Hard to maintain CSS
- No native heatmap support in Streamlit

### 6.2 Charting Library Options

| Library | Pros | Cons | Recommendation |
|---------|------|------|-----------------|
| **Plotly** | Interactive heatmap; hover tooltips; native Streamlit integration | Slightly verbose; not "lightweight" | ✅ **BEST** |
| **Altair** | Declarative; clean syntax; interactive | Less mature; fewer examples | Good alternative |
| **Matplotlib** | Simple; static | No interactivity; clunky in Streamlit | Avoid |
| **Folium** | Map-based; interactive | Not designed for heatmaps | Avoid |
| **Custom HTML/Canvas** | Full control | Requires JS; hard to maintain | Avoid (unless essential) |

### 6.3 Recommended Visualization (MVP)

**Use Plotly** to create:
1. **Heatmap Grid**: 9-zone strike zone with color intensity based on metric
2. **Hover Tooltips**: Show detailed stats per zone
3. **Color Scale Legend**: Map colors to metric values

```python
import plotly.graph_objects as go

def render_strike_zone_heatmap(zone_df, metric_type):
    """
    Create interactive strike zone heatmap.
    
    Args:
        zone_df: DataFrame with zone_id, x_min, x_max, y_min, y_max, metric_value, hover_text
        metric_type: str, e.g., "Pitch %", "Slugging %", "wOBA"
    
    Returns:
        plotly figure
    """
    fig = go.Figure()
    
    # Add rectangles for each zone
    for _, row in zone_df.iterrows():
        zone_id = row['zone_id']
        x_min, x_max = row['x_min'], row['x_max']
        y_min, y_max = row['y_min'], row['y_max']
        metric_value = row[metric_type.lower().replace(' ', '_').replace('%', 'pct')]
        hover_text = row['hover_text']
        
        color_intensity = metric_value / zone_df[...].max()  # Normalize 0-1
        color = f'rgba(255, {int(200 * (1 - color_intensity))}, 0, {0.7 + 0.3 * color_intensity})'
        
        fig.add_trace(go.Scatter(
            x=[x_min, x_max, x_max, x_min, x_min],
            y=[y_min, y_min, y_max, y_max, y_min],
            fill='toself',
            fillcolor=color,
            line=dict(color='#333', width=2),
            hovertext=hover_text,
            hoverinfo='text',
            showlegend=False,
        ))
    
    # Add strike zone border
    fig.add_shape(
        type="rect",
        x0=-0.8, y0=1.5, x1=0.8, y1=3.5,
        line=dict(color="black", width=3, dash="dash"),
        fillcolor="transparent",
    )
    
    fig.update_layout(
        title=f"Strike Zone: {metric_type}",
        xaxis_title="Horizontal Location (ft)",
        yaxis_title="Vertical Location (ft)",
        height=600,
        width=700,
        hovermode='closest',
    )
    
    return fig
```

### 6.4 Alternative UI Patterns

**Pattern 1: Tabbed Interface** (Recommended)
```
Pitcher Detail Page
├─ [Overview] [Strike Zone] [Splits] [Trends]
└─ Strike Zone Tab
    ├─ Dropdowns: Metric, Pitch Type, Handedness (optional)
    ├─ Plotly Heatmap
    └─ Stats Table (zone-by-zone breakdown)
```

**Pattern 2: Expandable Section** (Simpler; less intrusive)
```
Pitcher Detail Page
├─ [Existing content]
├─ [Expand "Strike Zone Analysis"]
└─ Strike Zone Section
    ├─ Dropdowns
    ├─ Heatmap
    └─ Stats table
```

**Pattern 3: Modal/Popup** (Too cluttered for Streamlit)

**Recommendation**: **Tabbed Interface** (Pattern 1). It's clean, scalable, and prepares for future tabs (Splits, Trends).

---

## PART 7: IMPLEMENTATION ROADMAP

### 7.1 MVP (Minimum Viable Product) — 16-24 hours

**Scope**: Basic strike zone grid with pitch % metric, all pitches, no filters

```
MVP Deliverables:
├─ Strike zone data fetching (pitcher_id → 9-zone aggregation)
├─ Pitch % metric calculation
├─ Plotly heatmap visualization
├─ Pitch type dropdown (All, 4-Seam, Slider, Cutter, Changeup)
├─ Integration into pitcher detail page
├─ Caching (300s TTL)
└─ Error handling (graceful fallback if data unavailable)
```

**Tasks** (in order):
1. **Set up dependencies** (pybaseball or Savant scraper alternative) — 2 hrs
2. **Create `strike_zone.py` module** with:
   - `load_pitch_location_data(player_id)` — fetches Statcast data
   - `aggregate_to_zones(statcast_df)` — converts raw data to 9-zone grid
   - `render_strike_zone_heatmap()` — Plotly visualization
3. **Integrate into pitcher detail page** — 4 hrs
   - Add Pitch Type dropdown
   - Add render call after Matchup Read section
   - Update session state for pitch type selection
4. **Test end-to-end** — 3 hrs
5. **Document** (code comments, README updates) — 2 hrs

**Estimated Time**: 16-20 hours  
**Difficulty**: MEDIUM (data aggregation is tricky; visualization is easy with Plotly)  
**Risks**: 
- Statcast data format changes
- Performance (if pybaseball is slow)
- Missing data for some pitchers

---

### 7.2 Phase 1 (Post-MVP) — 12-16 hours

**Scope**: Add metric dropdown, handedness filter, improve UI/UX

```
Phase 1 Additions:
├─ Metric dropdown: Pitch %, Total Pitches, Hits, HR, SLG, xSLG, AVG, xBA, wOBA, xwOBA
├─ Handedness filter: All, vs RHB, vs LHB
├─ Zone-by-zone stats table (sortable, clickable)
├─ Improved heatmap colors (use plotly's built-in color scales)
├─ Tooltip enhancements (show pitch counts, hit counts, etc.)
└─ Caching refinement (smart cache invalidation)
```

**Tasks**:
1. **Extend data layer** — `aggregate_to_zones()` to calculate all metrics — 4 hrs
2. **Add Metric dropdown** (UI) — 2 hrs
3. **Add Handedness filter** (UI + logic) — 3 hrs
4. **Add stats table** (sortable) — 3 hrs
5. **Enhance tooltips** — 2 hrs
6. **Test** — 2 hrs

**Estimated Time**: 12-16 hours  
**Difficulty**: EASY (mostly UI iteration)

---

### 7.3 Phase 2 (Advanced Metrics) — 10-12 hours

**Scope**: Expand to all requested metrics; add date range filter

```
Phase 2 Additions:
├─ Advanced metrics:
│   ├─ Barrel/BIP %
│   ├─ SLG (slugging %)
│   ├─ xSLG (expected slugging %)
│   ├─ AVG (batting average)
│   ├─ xBA (expected batting average)
│   ├─ wOBA (weighted on-base average)
│   └─ xwOBA (expected wOBA)
├─ Date range filter (start, end date)
├─ Season-to-date toggles (Last 30 days, Last 15 days, vs Full Season)
└─ Metric unit normalization (% vs count vs ratio)
```

**Tasks**:
1. **Add metric calculations** to `aggregate_to_zones()` — 4 hrs
2. **Add date range selector UI** — 2 hrs
3. **Add presets** (Last 15 days, Last 30 days, Full Season) — 2 hrs
4. **Test metrics accuracy against Savant/Statcast** — 3 hrs

**Estimated Time**: 10-12 hours  
**Difficulty**: MEDIUM (metric calculations need validation)

---

### 7.4 Phase 3 (Future Views) — 20-30 hours

**Scope**: Extend to batter detail view, pitcher comparison

```
Phase 3 Additions:
├─ Batter Detail Page
│   ├─ Strike zone showing where batter makes contact
│   ├─ Same metric dropdown
│   ├─ Pitch type breakdown (what types does batter hit hardest?)
│   └─ Handedness view (vs LHP, vs RHP)
├─ Pitcher vs Batter Comparison
│   ├─ Side-by-side strike zones
│   ├─ "Where pitcher throws vs where batter hits"
│   └─ Predictive insights
└─ Playoff/Historical Data
    ├─ Toggle between regular season, playoff, all-time
    └─ Trending charts
```

**Estimated Time**: 20-30 hours (includes new UI patterns, new views)  
**Difficulty**: HIGH (new architecture patterns needed)

---

### 7.5 Phase 4 (Production Hardening) — 15-20 hours

**Scope**: Performance, reliability, scalability

```
Phase 4 Additions:
├─ Local Database (SQLite)
│   ├─ Cache Statcast data locally
│   ├─ Incremental sync (only new data since last fetch)
│   └─ Offline capability
├─ Parallel API Calls
│   ├─ Fetch pitcher stats + strike zone data simultaneously
│   └─ Reduce page load time
├─ Performance Monitoring
│   └─ Log query times, cache hit rates, API errors
├─ Official Savant API or Trackman Partnership
│   └─ Replace scraping/pybaseball with official data source
└─ Unit Tests
    ├─ Test data aggregation logic
    ├─ Test metric calculations
    └─ Test visualization rendering
```

**Estimated Time**: 15-20 hours  
**Difficulty**: MEDIUM (mostly infrastructure)

---

### 7.6 Implementation Timeline

```
Timeline (Proposed):

Week 1 (Refactoring - OPTIONAL but recommended)
├─ Extract data layer → data_layer.py
├─ Extract components → components.py
└─ Add type hints to app.py

Week 2 (MVP)
├─ Research best data source (pybaseball vs Savant)
├─ Implement strike_zone.py with zone aggregation
├─ Integrate into pitcher detail page
└─ Test end-to-end

Week 3 (Phase 1)
├─ Add metric dropdown
├─ Add handedness filter
├─ Build stats table

Week 4 (Phase 2)
├─ Add advanced metrics
├─ Add date range filter
└─ Validate against Baseball Savant

Ongoing (Phases 3-4)
├─ Expand to batter views
├─ Add database layer
├─ Performance optimization
```

---

## PART 8: DIFFICULTY ESTIMATES

| Task | Complexity | Estimate | Blocker | Risk |
|------|-----------|----------|---------|------|
| **Set up data source** (pybaseball or Savant alt) | MEDIUM | 3 hrs | YES | HIGH (data source stability) |
| **Zone aggregation logic** (MVP) | MEDIUM | 4 hrs | YES | MEDIUM (metric calculations) |
| **Plotly heatmap MVP** | EASY | 3 hrs | NO | LOW |
| **Integrate into pitcher detail page** | EASY | 2 hrs | NO | LOW |
| **Add metric dropdown** | EASY | 2 hrs | NO | LOW |
| **Add handedness filter** | EASY | 2 hrs | NO | LOW |
| **Advanced metrics (all 7)** | MEDIUM | 6 hrs | NO | MEDIUM (validation) |
| **Date range filter** | EASY | 2 hrs | NO | LOW |
| **Batter detail view** | HARD | 12 hrs | NO | MEDIUM (new UI patterns) |
| **Pitcher comparison** | HARD | 8 hrs | NO | LOW |
| **Local database + caching** | HARD | 10 hrs | NO | MEDIUM (SQLite optimization) |
| **Refactor to modular architecture** | MEDIUM | 10 hrs | NO | LOW |
| **Unit tests** | MEDIUM | 8 hrs | NO | LOW |

**Total Effort**: 72-90 hours (MVP = 16-20 hrs; Full Advanced = 72-90 hrs)

---

## PART 9: SUGGESTED IMPROVEMENTS TO YOUR VISION

### 9.1 Enhancements to Consider

**1. Zone Location Labels**  
Currently your zones are numeric (1-9). Consider adding labels:
```
         High
     NW   N   NE
     W    C   E    (C = Center/Strike Zone)
     SW   S   SE
         Low
```
This makes tooltips and discussions easier ("He throws a lot on the middle-in").

**2. "Pitch Value" Metric (Advanced)**  
Beyond wOBA, consider showing "pitch value" (how many runs this pitch is worth per 100 throws):
```
Pitch Value = (Expected Run Value - League Average) * Pitch Count
```
This combines frequency + effectiveness into one metric.

**3. "Relative to Pitcher Average" View**  
Allow filtering zones by "above/below pitcher's average pitch location":
```
Instead of absolute %, show "Pitch location vs pitcher's average"
Green zones = pitcher throws more here than usual
Red zones = pitcher throws less here than usual
```
Useful for "When is he attacking outside vs inside?"

**4. Batter Spray Chart Integration**  
When viewing pitcher strike zone, overlay batter's "spray chart" (where they hit balls):
```
Strike Zone Grid:
  └─ Pitcher throws here
     (heatmap: where pitcher throws)
  
Overlay:
  └─ Batter hits here
     (scatter plot: hit locations)
```
Visual = "Where pitcher throws" vs "Where batter makes contact" → matchup edge.

**5. Confidence/Sample Size Indicator**  
Show which zones have sufficient data:
```
Zone 5 (Center): 45 pitches (solid sample) → opaque
Zone 9 (Low-away): 3 pitches (small sample) → semi-transparent
```
Prevents over-interpreting small samples.

**6. "Trend Arrow" in Each Zone**  
Show if pitcher is throwing more/less to each zone over time:
```
Zone shows: "32%" + "↑" (trending up)
        or: "32%" + "↓" (trending down)
```
Quick visual for patterns (e.g., "He's throwing more high heat this season").

**7. Multi-Pitcher Comparison Mode** (Phase 3)
```
Comparison View:
  ├─ Pitcher A Strike Zone (left heatmap)
  ├─ vs (comparison metric in center)
  └─ Pitcher B Strike Zone (right heatmap)

Comparison Metric Options:
  ├─ Side-by-side difference (A% - B%)
  ├─ Pitcher A's zones where B struggles
  └─ Distribution comparison (who's more "predictable"?)
```

**8. GIF/Animation Mode** (Fun but lower priority)
```
Animate strike zone zones "lighting up" in order of pitch frequency
Visual representation of pitcher's sequencing patterns
```

### 9.2 Alternative Architectures to Consider

**Option A: Tabs Layout (Recommended)**
```
Pitcher Detail Page
├─ Overview (current stats, arsenal)
├─ Strike Zone (new heatmap)
├─ Splits (vs LHB/RHB breakdown)
└─ Trends (historical performance)
```
✅ Clean, scalable, room for growth  
⚠️ Requires refactoring pitcher detail page

**Option B: Carousel/Scroll** (Alternative)
```
Pitcher Detail Page
├─ Scroll horizontally through analysis views
├─ Overview → Strike Zone → Splits → Trends
└─ Mobile-friendly
```
⚠️ Less discoverable on desktop; Streamlit not great at horizontal scroll

**Option C: Right-Side Sidebar** (Alternative)
```
Left: Current stats, lineup  |  Right: Strike Zone Heatmap
```
⚠️ Requires custom CSS; Streamlit sidebar is left-only

---

## PART 10: DATA QUALITY & VALIDATION

### 10.1 Known Data Issues

**Issue 1: Pitch Type Naming Inconsistency**  
Baseball Savant vs MLB Stats vs pybaseball use different pitch type names:
```
Savant: "4-Seam Fastball"
MLB Stats: "FF" (pitch code)
pybaseball: "4-Seam Fastball" (inconsistent capitalization)

Solution: Standardize naming in data layer
```

**Issue 2: Location Data Gaps**  
Some older games may not have detailed location data:
```
Pre-2015: Limited data
2015-present: Most games covered
Live games: May not have data until 24hrs after completion

Solution: Show "Data unavailable" gracefully; show data freshness timestamp
```

**Issue 3: Metrics Calculation Edge Cases**  
```
wOBA for pitcher requires: (HBP + 0.69*BB + 0.72*HBP + 0.97*1B + 1.28*2B + 1.58*3B + 1.95*HR) / (AB+BB+HBP+SF)

Edge cases:
- Pitcher with 0 batters faced (shouldn't happen but could)
- Metric = N/A if denominator < 5 (small sample)

Solution: Only show metrics if sample size > 10 pitches in zone
```

### 10.2 Validation Strategy

**Before going to production**:
1. Spot-check 5 random pitchers against Baseball Savant website
2. Verify metric calculations match official sources (FanGraphs, Baseball Savant)
3. Test with edge cases (2-pitch pitcher, relief pitcher, etc.)
4. Monitor for Statcast/Savant data format changes

---

## PART 11: TECHNICAL RECOMMENDATIONS

### 11.1 Before Building Strike Zone (Refactoring Prerequisites)

**Critical** (do before strike zone):
- [ ] Evaluate data source (pybaseball vs Savant HTML scraping)
- [ ] Set up local caching for API responses
- [ ] Add error handling for network failures

**Important** (nice to have before):
- [ ] Extract `data_layer.py` (centralize all API calls)
- [ ] Extract `components.py` (reusable card components)
- [ ] Add configuration file for constants

**Nice** (can do after):
- [ ] Add unit tests for aggregation logic
- [ ] Refactor inline CSS to theme file
- [ ] Add type hints

### 11.2 Architecture for Strike Zone Feature

```python
# Proposed file structure after strike zone addition:

BaseballDashboard/
├── app.py                      # Main Streamlit app (orchestrator)
├── data_layer.py               # All API calls & caching (OPTIONAL refactor)
│   ├── load_schedule()
│   ├── load_pitcher_stats()
│   ├── get_savant_arsenal_for_player()
│   └── load_pitch_location_data()  # NEW
├── strike_zone.py              # Strike zone logic (NEW)
│   ├── aggregate_to_zones()
│   ├── calculate_metrics()
│   └── render_strike_zone_heatmap()
├── components.py               # Reusable UI components (OPTIONAL)
│   ├── stat_card()
│   ├── lineup_display()
│   └── matchup_read_card()
├── config.py                   # Constants & configuration (OPTIONAL)
│   ├── ZONE_DEFINITIONS
│   ├── COLORS
│   ├── API_CACHE_TTL
│   └── TEAM_LOGOS_URL
├── PROJECT_OVERVIEW.md
├── DEVELOPER_NOTES.md
├── TODO.md
└── ARCHITECTURE_REVIEW_STRIKE_ZONE.md
```

### 11.3 Specific Code Patterns to Use

**Pattern 1: Data Fetching with Caching**
```python
@st.cache_data(ttl=300)
def load_pitch_location_data(player_id, pitch_type=None, vs_handedness=None):
    """
    Fetch Statcast data for pitcher's pitches.
    
    Args:
        player_id: Pitcher ID
        pitch_type: Filter to specific pitch type (optional)
        vs_handedness: Filter to R/L hitters (optional)
    
    Returns:
        pd.DataFrame with columns: pitcher_id, pitch_type, location_x, location_y, 
                                   result, exit_velocity, launch_angle, is_barrel, etc.
    """
    try:
        # Fetch from pybaseball or Savant
        df = fetch_statcast_data(player_id)
        if pitch_type:
            df = df[df['pitch_type'].str.lower() == pitch_type.lower()]
        if vs_handedness:
            df = df[df['batter_side'] == vs_handedness]
        return df
    except Exception as e:
        logger.error(f"Failed to fetch pitch location data: {e}")
        return pd.DataFrame()
```

**Pattern 2: Zone Aggregation**
```python
def aggregate_to_zones(statcast_df, num_zones=9):
    """
    Aggregate pitch data into zone grid.
    
    Returns:
        pd.DataFrame with columns: zone_id, zone_label, x_min, x_max, y_min, y_max,
                                   pitch_count, hit_count, slug_pct, woba, etc.
    """
    # Define zone boundaries
    zones = define_zone_boundaries(num_zones)
    
    # For each zone, filter pitches and calculate metrics
    zone_stats = []
    for zone_id, (x_min, x_max, y_min, y_max) in zones.items():
        zone_pitches = statcast_df[
            (statcast_df['px'] >= x_min) & (statcast_df['px'] <= x_max) &
            (statcast_df['pz'] >= y_min) & (statcast_df['pz'] <= y_max)
        ]
        
        if len(zone_pitches) == 0:
            continue
        
        stats = {
            'zone_id': zone_id,
            'pitch_count': len(zone_pitches),
            'hit_count': len(zone_pitches[zone_pitches['type'] == 'X']),
            'slug_pct': calculate_slug(zone_pitches),
            'woba': calculate_woba(zone_pitches),
            # ... other metrics
        }
        zone_stats.append(stats)
    
    return pd.DataFrame(zone_stats)
```

**Pattern 3: Session State for Dropdowns**
```python
# In pitcher detail page:
if st.session_state.get("selected_pitcher"):
    # Initialize dropdown state
    if 'strike_zone_metric' not in st.session_state:
        st.session_state['strike_zone_metric'] = 'Pitch %'
    if 'strike_zone_pitch_type' not in st.session_state:
        st.session_state['strike_zone_pitch_type'] = 'All'
    
    # Render dropdowns
    col1, col2, col3 = st.columns(3)
    with col1:
        selected_metric = st.selectbox(
            "Metric",
            ["Pitch %", "Total Pitches", "Hits", "HR", "SLG", "xSLG", "wOBA", "xwOBA"],
            key="strike_zone_metric"
        )
    with col2:
        selected_pitch_type = st.selectbox(
            "Pitch Type",
            ["All"] + pitcher_arsenal_list,  # Dynamic from arsenal data
            key="strike_zone_pitch_type"
        )
    
    # Fetch data
    zone_data = load_pitch_location_data(pitcher_id, selected_pitch_type)
    zone_agg = aggregate_to_zones(zone_data)
    
    # Render visualization
    fig = render_strike_zone_heatmap(zone_agg, selected_metric)
    st.plotly_chart(fig, use_container_width=True)
```

---

## PART 12: FINAL RECOMMENDATIONS & PRIORITIES

### 12.1 Do This First (Before Strike Zone Coding)

**Priority 1: Choose Data Source** (BLOCKER - 2 hrs)
- [ ] Test `pybaseball.statcast()` with a recent pitcher
- [ ] Compare quality/speed vs Baseball Savant HTML scraping
- [ ] Decision: pybaseball (MVP) + plan for official API later

**Priority 2: Decide on Refactoring** (OPTIONAL but recommended - 8-10 hrs)
- [ ] YES: Extract `data_layer.py` + `components.py` before strike zone
- [ ] NO: Build strike zone in app.py, refactor later
- Recommendation: **YES** - Will make strike zone easier to build and maintain

**Priority 3: Design Zone Grid** (1 hr)
- [ ] Finalize 9-zone vs 12-zone decision
- [ ] Define exact boundaries (coordinate ranges)
- [ ] Create zone_id → label mapping

### 12.2 MVP Implementation Order

```
1. Data Source Decision (2 hrs)
2. Create strike_zone.py module (6 hrs)
   ├─ load_pitch_location_data()
   ├─ aggregate_to_zones()
   └─ render_strike_zone_heatmap()
3. Integrate into pitcher detail page (2 hrs)
4. Add pitch type dropdown (2 hrs)
5. Test & debug (3 hrs)
6. Deploy MVP (1 hr)

TOTAL MVP: 16 hours
```

### 12.3 Go/No-Go Checklist for MVP

**Before launching MVP, ensure**:
- [ ] Zone aggregation logic validated against 3 sample pitchers
- [ ] Plotly heatmap renders without errors
- [ ] Dropdown filters work (all pitches, 4-seam, slider, etc.)
- [ ] Caching works (load time < 2s after first fetch)
- [ ] Error handling for missing data (shows "Data unavailable" gracefully)
- [ ] Code documented with docstrings
- [ ] No breaking changes to existing pitcher detail page

### 12.4 Phased Delivery Plan

```
SPRINT 1 (MVP - 3 weeks)
└─ Basic strike zone, pitch % metric, pitch type dropdown
   Expected: ✅ Live on dev branch by end of week 2

SPRINT 2 (Phase 1 - 2 weeks)
└─ Metric dropdown, handedness filter, stats table
   Expected: ✅ Live on main by end of week 4

SPRINT 3 (Phase 2 - 2 weeks)
└─ Advanced metrics, date range filter, validations
   Expected: ✅ Live on main by end of week 6

LATER (Phase 3+)
└─ Batter views, comparisons, database layer, tests
   Expected: Q3 2026
```

---

## CONCLUSION

The Interactive Strike Zone Analysis Grid is an **excellent next feature** for your Prop Lab. Your current codebase is well-organized and will support this feature—though some refactoring beforehand will make development smoother.

**Key Takeaways**:
1. ✅ Your architecture is sound; this feature fits naturally into the pitcher detail page
2. ⚠️ Biggest risk: Statcast/Savant data source stability (use pybaseball for MVP)
3. 🎯 Estimated MVP delivery: 16-20 hours of focused work
4. 🚀 This feature unlocks future views (batters, comparisons, trends)
5. 💡 Consider the suggested improvements (zone labels, pitch value, trends) for Phase 2+

**Next Steps**:
1. Review this document with your team
2. Decide on refactoring (extract data layer or build in-app.py)
3. Choose data source (pybaseball recommended)
4. Scope exact MVP deliverables
5. Begin implementation sprint

---

**Document Version**: 1.0  
**Last Updated**: June 18, 2026  
**Reviewed By**: Senior Software Architect (AI)  
**Status**: Ready for Implementation

