# DEVELOPER_NOTES.md — Guidelines for Future Development

## Most Important Functions

### 1. `load_schedule(game_date)` — Core Data Foundation
**Location**: ~line 120
**Importance**: HIGH — Every feature depends on this
**What it does**: 
- Fetches all MLB games for a given date
- Enriches with pitcher info and handedness
- Sorts by game status (non-final first, then by time)
- Returns DataFrame with all game metadata

**Key responsibilities**:
- Calls `get_players_info()` to fetch pitcher handedness
- Hydrates schedule with `probablePitcher`, `team`, `venue`
- Returns sorted DataFrame used by entire app

**Cache TTL**: 120 seconds
**Do NOT change**: The DataFrame column names (used throughout app)

**Safe to extend**:
- Add new fields from schedule API response (e.g., temp, wind)
- Add new hydration parameters
- Enhance sorting logic

---

### 2. `load_lineups(game_pk)` — Game Lineup Provider
**Location**: ~line 155
**Importance**: HIGH — Required for pitcher detail and slate views
**What it does**:
- Fetches away and home lineups for a game
- Extracts player ID, name, number, handedness, position
- Handles fallback to player info API if handedness missing

**Returns**: (away_lineup, home_lineup) — list of dicts with keys:
- `number`, `player_id`, `name`, `handedness`, `position`

**Cache TTL**: 120 seconds
**Do NOT change**: The dict structure (used everywhere lineups display)

**Safe to extend**:
- Add stats (BA, HR, RBIs) to lineup items
- Add team color or other metadata
- Enhance position abbreviations

---

### 3. `load_pitcher_stats(player_id)` — Season Statistics
**Location**: ~line 215
**Importance**: HIGH — Feeds Pitcher Stats card
**What it does**:
- Fetches 2026 season pitching statistics for a pitcher
- Returns dict with ERA, WHIP, K%, BB%, IP, HR allowed

**Returns dict keys**: `era`, `whip`, `k_percent`, `bb_percent`, `innings_pitched`, `hr_allowed`

**Cache TTL**: 180 seconds
**Do NOT change**: Return dict keys (used in stat card rendering)

**Safe to extend**:
- Add new stats (e.g., GB%, ERA+, FIP)
- Add game-by-game splits
- Add left/right splits (implement vs. batter splits here)

---

### 4. `get_savant_arsenal_for_player(player_id)` — Pitch Type Data
**Location**: ~line 326
**Importance**: HIGH — Provides pitch arsenal display
**What it does**:
- Scrapes Baseball Savant player page
- Extracts pitch types, counts, velocities for current season
- Uses JSON extraction helper `_find_json_objects_for_player_page()`

**Returns**: List of dicts with keys: `pitch_type_name`, `pitches_thrown`, `avg_speed`, etc.

**Cache TTL**: 180 seconds
**⚠️ FRAGILE**: HTML parsing depends on Savant page structure
- If scrape fails, logged but graceful fallback exists
- Empty list treated as "data unavailable"

**Safe to extend**:
- Add additional stats from player page (e.g., spin rate, extension)
- Improve JSON extraction logic
- Add try/except for structure changes

**Be careful changing**:
- The JSON marker parsing (`'"pitch_type_name"'`)
- Field name extractions in JSON object

---

### 5. Pitcher Detail Page Rendering
**Location**: ~line 420-620 (session state based)
**Importance**: HIGH — User-facing pitcher matchup view
**Structure**:
1. Check session state for selected pitcher & game
2. Load lineups and stats
3. Count opposing batter handedness
4. Render title and metadata
5. Render Pitcher Stats cards (3-column grid)
6. Render Matchup Read card
7. Render Opposing Lineup
8. `st.stop()` to prevent slate rendering

**Do NOT change**:
- Session state keys: `selected_pitcher`, `selected_game`
- The `st.stop()` call (prevents double rendering)

**Safe to extend**:
- Add new card sections (insert before/after Matchup Read)
- Modify card styling (adjust border, padding, colors)
- Add new stat displays within existing cards
- Extend metadata display (add more game info)

**Careful editing**:
- Variable names used across multiple sections:
  - `mlb_stats` (ERA, WHIP, K%, BB%, IP, HR)
  - `savant_arsenal_rows` (pitch type data)
  - `opponent_lineup`, `rhb_count`, `lhb_count`, `switch_count`
  - `fastball_value`, `breaking_value`, `offspeed_value`, `primary_pitch`
- These are reused in multiple card sections

---

## Safe to Edit Sections

### 1. Styling & Colors
**Locations**: Inline HTML/CSS in markdown sections
- Card borders: `border:1px solid #e5e7eb`
- Background: `background:#ffffff`
- Shadows: `box-shadow:0 1px 2px rgba(0,0,0,0.04)`
- Padding/margins: adjustable

**Approach**:
- Modify values in `st.markdown()` calls
- Test in browser for visual consistency
- Keep border-radius and shadow consistent across cards

### 2. Card Layout & Content
**What's safe**:
- Reorder stat cards (adjust column sequence)
- Add new stat rows to grid layouts
- Change label text
- Modify display formatting (`format_number()` params)
- Add/remove rows in `grid-template-columns` layouts

**What's risky**:
- Changing variable names (used downstream)
- Removing stat values (breaks other sections)
- Changing dict keys returned from API functions

### 3. Display Formatting
**Safe to change**:
- `format_number(value, precision=2, suffix="")`
  - Adjust precision: precision=0 for integers, precision=1 for decimals
  - Add/remove suffix: suffix="%" for percentages, suffix=" IP" for innings
- Number rounding logic
- N/A display text

### 4. Helper Functions
**Safe to add/modify**:
- `eastern_time()` — time format changes, timezone adjustments
- `format_pitcher_hand()` — display text changes
- `display_status()` — status text mapping
- `status_color()` — color values
- `format_number()` — precision, formatting

**Safe to add**: New helper functions for math, text, or display

---

## Sections Requiring Careful Edits

### 1. Data Fetching Functions (Caching Logic)
**Why careful**: Cache decorators and TTLs affect performance
- `@st.cache_data(ttl=120)` — session cache timeout
- Changing TTL affects data freshness vs. performance
- Adding/removing cache breaks existing behavior

**Before editing**:
- Understand the full function (start to return)
- Check where output is consumed
- Test cache behavior (hard refresh browser)
- Document cache invalidation needs

**Safe changes**:
- TTL adjustments (increase/decrease timeout)
- Adding new fields to returned dict (don't remove existing)
- Improving error handling

**Dangerous changes**:
- Removing cache decorator (app will be slower)
- Changing return dict structure (breaks consumers)
- Adding new API calls without optimization

### 2. Session State Management
**Current usage**:
```python
st.session_state['selected_pitcher'] = {
    'name': game.get('away_pitcher'),
    'id': game.get('away_pitcher_id'),
    'hand': game.get('away_pitcher_hand'),
    'side': 'away'
}
st.session_state['selected_game'] = game['game_pk']
st.session_state['selected_date'] = date
st.session_state['games'] = DataFrame
```

**Before editing**:
- List all session keys used in app (search `st.session_state`)
- Understand flow (where set, where read, where cleared)
- Test navigation between views

**Safe changes**:
- Adding new session keys
- Adding state values to existing keys
- Modifying state in conditional blocks

**Dangerous changes**:
- Renaming session keys (breaks navigation)
- Removing `st.session_state.pop()` in back buttons
- Removing `st.rerun()` calls (UI won't update)

### 3. API Parameters & Hydration
**Locations**: API calls to MLB Stats and Savant
**Examples**:
- `hydrate: "probablePitcher,team,venue"`
- `group: "pitching"`
- `stats: "season"`
- `year: str(date.today().year)`

**Before changing**:
- Check MLB Stats API documentation
- Understand what each parameter does
- Verify return structure
- Update fallback handling if response changes

**Safe changes**:
- Adding new hydration parameters
- Adding filters (e.g., `limit`, `offset`)
- Updating year dynamically

**Dangerous changes**:
- Removing critical hydration
- Changing stat type (breaks expected fields)
- Modifying API URLs without testing

### 4. Opposing Lineup Handedness Counting
**Location**: Pitcher detail page, ~line 470-475
```python
rhb_count = sum(1 for p in opponent_lineup if p.get("handedness") == "R")
lhb_count = sum(1 for p in opponent_lineup if p.get("handedness") == "L")
switch_count = sum(1 for p in opponent_lineup if p.get("handedness") == "S")
```

**Why careful**: 
- These counts are used in multiple places (Matchup Context, Matchup Read)
- Lineup data comes from multiple sources (may be incomplete early in day)
- Missing handedness data skews counts

**Before changing**:
- Test with lineups that have missing/incomplete handedness
- Verify counts match what players actually are
- Check if "S" (switch) is properly detected

**Safe changes**:
- Add new counts (e.g., "unknown" count)
- Add minimum game checks
- Improve data validation

---

## How to Add Future Stats/Cards

### Step 1: Identify Data Source
- **Already available**: Use existing load functions
- **New source**: Create new `load_X_data()` function with cache
- **API endpoint**: Determine parameters and return structure

### Step 2: Create/Extend Data Function
```python
@st.cache_data(ttl=180)
def load_pitcher_splits(player_id):
    """Fetch L/R splits for pitcher"""
    stats_url = f"https://statsapi.mlb.com/api/v1/people/{player_id}/stats"
    params = {
        "stats": "vsLeft,vsRight",
        "season": str(date.today().year),
    }
    response = requests.get(stats_url, params=params, timeout=15)
    if response.status_code != 200:
        return {}
    
    payload = response.json()
    splits = payload.get("stats", [])
    # Extract and return relevant data
    return {...}
```

### Step 3: Call Function in Pitcher Detail
```python
try:
    pitcher_splits = load_pitcher_splits(pid)
except Exception as e:
    pitcher_splits = {}
    logger.error("Splits request failed for %s: %s", pid, e)
```

### Step 4: Create Styled Card
Follow existing card pattern:
```python
st.markdown(
    "<div style='border:1px solid #e5e7eb; border-radius:12px; padding:14px; ...'>"
    "<div style='font-weight:700; margin-bottom:10px;'>Card Title</div>"
    "<div style='display:grid; grid-template-columns:1fr auto; row-gap:8px; ...'>"
    f"<span>Label</span><span>{value}</span>"
    "</div></div>",
    unsafe_allow_html=True,
)
```

### Step 5: Add to Layout
Insert in pitcher detail page before/after existing cards:
```python
# After Pitcher Stats cards
st.markdown("---")

# NEW CARD HERE
st.markdown("### New Stat Section")
st.markdown("<div style='...'>...</div>", unsafe_allow_html=True)

# Before Opposing Lineup
st.markdown("---")
st.markdown("### Opposing Lineup")
```

### Best Practices
- Keep card styling consistent with existing cards
- Use `format_number()` for stat display
- Handle missing data gracefully (show "N/A")
- Add logging for data fetch issues
- Test with 2-3 real pitchers before deployment

---

## Notes About Pitcher Detail Page

### Entry Point
- User clicks pitcher name in slate view game card
- Button click handler sets session state and calls `st.rerun()`

### Flow
1. Check `st.session_state.get("selected_pitcher")`
2. If set, load game and lineups
3. Determine `side` (away/home) from state
4. Get opponent team and lineup based on side
5. Count opponent handedness
6. Render pitcher header (name, team, opponent, game info)
7. Load stats and render cards
8. Render opposing lineup
9. Call `st.stop()` to prevent slate rendering

### Important Variables
- `side`: "away" or "home" — determines opponent team
- `opponent_lineup`: List of batter dicts
- `rhb_count`, `lhb_count`, `switch_count`: Opposing lineup splits
- `mlb_stats`: Dict with ERA, WHIP, etc.
- `savant_arsenal_rows`: List of pitch type data

### Navigation Back
```python
if st.button("← Back to Slate"):
    st.session_state.pop("selected_pitcher", None)
    st.session_state.pop("selected_game", None)
    st.rerun()
```
- Clears state and reruns app
- Returns to slate view with current date

### Adding New Sections
- Insert between existing `st.markdown()` blocks
- Use same variable names (don't reload data)
- Keep variables in scope from initial load
- Insert `st.markdown("---")` separator before new sections

---

## Notes About MLB Stats API

### Base URL
`https://statsapi.mlb.com/api/v1`

### Commonly Used Endpoints
1. **Schedule**: `/schedule?sportId=1&date=YYYY-MM-DD&hydrate=probablePitcher,team,venue`
2. **Player Stats**: `/people/{personId}/stats?stats=season&group=pitching`
3. **Game Feed**: `/game/{gamePk}/feed/live`
4. **Player Info**: `/people?personIds=ID1,ID2,...`
5. **Splits**: `/people/{personId}/stats?stats=vsLeft,vsRight`

### Response Structure
- All endpoints return JSON with nested `data` objects
- Error handling: Check `response.status_code`
- Rate limiting: Generally unlimited for public endpoints, but cache aggressively

### Caching Strategy
- Schedule: 120 seconds (games update frequently)
- Stats: 180 seconds (historical data, slower to change)
- Lineups: 120 seconds (posted 30 min before game)
- Player info: 43200 seconds (12 hours, changes rarely)

---

## Notes About Baseball Savant

### URL Structure
- **Leaderboard**: `https://baseballsavant.mlb.com/leaderboard/pitch-arsenal-stats?type=pitcher&year=YYYY`
- **Player Page**: `https://baseballsavant.mlb.com/savant-player/{player_id}`

### Scraping Approach
- HTML page contains embedded JSON data
- Look for marker: `var data = [...]` or `var leaderboardData = [...]`
- Extract JSON block using bracket depth counting
- Parse resulting JSON

### Data Available
- Pitch type name, usage %, velocity, spin rate, etc.
- Year-to-date seasonal data
- Both all-purpose and split data

### Fragility Issues
1. **HTML changes**: If Savant restructures page, markers change
2. **Slow response**: Takes 2-3 seconds per request (no API)
3. **No official API**: Scraping is unsupported, may break
4. **Fallback needed**: App must handle empty/failed scrapes

### Fallback Strategy
```python
if len(pitch_type_counts) < 2:
    logger.warning("Pitch Arsenal N/A for player_id=%s", pid)
    actual_arsenal = []
    fastball_value = "N/A"
    # ... show N/A values
else:
    # ... calculate percentages
```

### Improvement Ideas
- Cache at database level (not just session)
- Batch request multiple pitchers if possible
- Monitor for page structure changes
- Consider StatsBomb or Trackman partnerships for official API

---

## Debugging Guide

### Common Issues

1. **"Pitch usage data unavailable"**
   - Cause: Less than 2 pitch types scraped from Savant
   - Check: logs for scrape URL and response
   - Fix: Wait for more season data, or switch data source

2. **"Lineup not posted yet"**
   - Cause: Accessing lineup before 30 min before game
   - Check: Game status and time
   - Expected: Normal before games start

3. **Slow loading**
   - Cause: Savant scrape takes 2-3s per pitcher
   - Check: Network speed, Savant responsiveness
   - Fix: Increase cache TTL, pre-fetch common pitchers

4. **Missing handedness in lineup**
   - Cause: Data not in game feed, fallback API didn't return
   - Check: logs for player info API calls
   - Fix: Retry, or mark as unknown

### Logging
- All API errors logged at ERROR level
- Informational messages at INFO level
- Debug messages at DEBUG level
- Check `logger.debug()` calls for detailed flow

### Testing
- Test with past game dates (complete data available)
- Test with future dates (incomplete lineups)
- Test with games in progress
- Test with finished games (status = FINAL)

---

## Performance Notes

### Load Time Breakdown
- MLB schedule fetch: ~0.5s
- Lineup fetch per game: ~0.5s each (cached)
- Pitcher stats: ~0.3s each (cached)
- Savant scrape per pitcher: ~2-3s each (cached, slow!)

### Optimization Ideas
1. **Pre-cache popular pitchers**: Load top 10 pitchers on page load
2. **Parallel requests**: Use threading/async for multiple API calls
3. **Database caching**: Store historical stats locally
4. **Lazy load**: Load Savant data only when pitcher detail clicked

### Current Caching
- Session-level caching (Streamlit cache_data decorator)
- TTLs: 120-180 seconds during session
- Hard refresh (Ctrl+Shift+R) clears cache
- No persistent disk cache

---

## Future API Considerations

### Moving Away from Savant Scraping
**Timeline**: After 50+ games (more reliable data)
**Options**:
1. Official partnership with Savant/StatsBomb
2. Trackman integration (if pitchers have devices)
3. Retrosheet historical data
4. Fan-created APIs (RotoWire, ESPN)

### Splitting Concerns
**Consider creating separate module**:
- `mlb_stats_api.py` — MLB Stats calls
- `savant_scraper.py` — Savant HTML extraction
- `database.py` — Local caching layer
- `formatters.py` — Display formatting

**Benefits**: Easier to test, swap data sources, reuse in other projects

---

**Last Updated**: 2026-06-17
**Next Review**: After pitcher vs. batter splits implementation
