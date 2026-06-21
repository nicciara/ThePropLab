# Baseball Dashboard Project Overview

## Project Name
🧪 **The Prop Lab** — MLB Baseball Prop Trading Dashboard

## Current Features

### 1. Multi-Sport Header with Sport Selector
- Dropdown selector for MLB, NBA, NFL, NHL, WNBA
- Currently only MLB is fully implemented; other sports show "coming soon" placeholder
- Sport selector in top-right corner

### 2. Game Schedule & Slate View
- **Date Navigation**: Previous day (←), date display, next day (→), Today button
- **Calendar Picker**: Expandable calendar to jump to any date
- **Game Cards**: Two-column layout displaying:
  - Team logos (away @ home)
  - Game time (ET)
  - Venue name
  - Game status (SCHEDULED, WARM UPS, IN PROGRESS, FINAL)
  - Status color coding (blue=scheduled, yellow=warmups, orange=in progress, red=final)
  - Load time and API call metrics in footer

### 3. Pitcher Detail Page
- **Accessed via**: Clicking on a pitcher name in the slate view
- **Layout**:
  - Pitcher name, hand (LHP/RHP), team, opponent, game info, venue, status
  - **Pitcher Stats Card**: ERA, WHIP, K%, BB%, HR Allowed, IP
  - **Pitch Arsenal Card**: Primary Pitch, Fastball %, Breaking Ball %, Offspeed %, Avg Velo, Actual Arsenal (detailed pitch type list)
  - **Matchup Context Card**: Opponent, opposing batters count, RHB/LHB/Switch splits
  - **Matchup Read Card** (NEW): Compact grid showing primary pitch, arsenal lean, opposing lineup, key stats
  - **Opposing Lineup**: Full list of opposing batters with numbers, names, handedness, positions
- **Back Button**: Returns to slate view

### 4. Lineups Display
- **Slate View**: Compact lineup list for each team (away & home) in game cards
- **Pitcher Detail**: Opposing lineup shown with full player details
- Shows player number, name, handedness (R/L/S), and position
- Displays "Lineup not posted yet" if not available

## Current Dashboard Layout

### Slate View (Default)
```
Header Row
  [← Logo] [Title] [Sport ▼]

Navigation Row
  [←] [Monday, June 17, 2026] [→] [Today] [Calendar ▼]

Success Message
  "Loaded X games | player API calls: Y | total load time: Z.XXs"

Game Cards (2-column grid)
  ┌─────────────────────┐ ┌─────────────────────┐
  │ [AWAY LOGO] @ [HOME]│ │ [AWAY LOGO] @ [HOME]│
  │ 🕒 Time | Status   │ │ 🕒 Time | Status   │
  │                     │ │                     │
  │ Away Team   Home Team│ │ Away Team   Home Team│
  │ Pitcher...  Pitcher  │ │ Pitcher...  Pitcher │
  │ Lineup      Lineup   │ │ Lineup      Lineup  │
  └─────────────────────┘ └─────────────────────┘
```

### Pitcher Detail View
```
[← Back to Slate]

Title: Pitcher Name (Hand)
Team: XXX
Opponent: YYY
Game: Away @ Home — Time ET
Venue: Stadium Name
Status: SCHEDULED/IN PROGRESS/FINAL

### Pitcher Stats
┌────────────────────────────────────────────────┐
│ 2026 Season Card │ Pitch Arsenal Card │ Matchup Context │
│ ERA / WHIP / K% │ Primary Pitch      │ Opponent / RHB  │
│ BB% / HR Allowed│ Fastball/Breaking  │ LHB / Switch    │
│ IP              │ Offspeed / Avg Velo│                 │
│                 │ [Actual Arsenal]   │                 │
└────────────────────────────────────────────────┘

### Matchup Read
┌────────────────────────────────────────────────┐
│ Primary pitch | Arsenal | Opposing lineup    │
│ ERA / WHIP    | IP                            │
│ K% / BB%      | HR Allowed                    │
└────────────────────────────────────────────────┘

### Opposing Lineup
- 1. Player Name (R) DH
- 2. Player Name (L) SS
...
```

## Data Sources Used

### 1. **MLB Stats API** (`statsapi.mlb.com`)
- **Schedule Endpoint**: `/api/v1/schedule`
  - Gets games for a given date
  - Returns: game PK, teams, probable pitchers, game status, game time, venue
  - Hydration: `probablePitcher`, `team`, `venue`

- **Pitcher Stats Endpoint**: `/api/v1/people/{player_id}/stats`
  - Gets season pitching stats for a specific pitcher
  - Returns: ERA, WHIP, K/9, BB/9, IP, HR allowed
  - Filters: `stats=season`, `group=pitching`, current year

- **Game Feed Endpoint**: `/api/v1.1/game/{game_pk}/feed/live`
  - Gets full game details including lineups
  - Extracts: batting order, player handedness, positions

- **Player Info Endpoint**: `/api/v1/people`
  - Gets player handedness (bat/pitch side)
  - Used as fallback when data not in game feed

### 2. **Baseball Savant** (`baseballsavant.mlb.com`)
- **Pitch Arsenal Leaderboard**: `/leaderboard/pitch-arsenal-stats`
  - Scrapes HTML page and extracts JSON for all pitcher pitch type data
  - Returns: pitch type name, usage %, velocity

- **Player Pitch Arsenal Page**: `/savant-player/{player_id}`
  - Scrapes HTML to get season pitch type data for individual pitcher
  - Parses JSON objects embedded in page HTML
  - Returns: pitch types, counts, velocities, year

## How to Run the App

### Prerequisites
- Python 3.8+
- Streamlit installed: `pip install streamlit`
- Required packages: `pandas`, `requests`

### Running Locally
```bash
cd c:/Users/nicci/OneDrive/Documents/BaseballDashboard
streamlit run app.py
```

### Expected Output
- Local URL: `http://localhost:8501` (opens automatically)
- Loads current day's MLB schedule by default
- Fetches ~20-30 pitcher profiles on first load (expect 2-5 second load time)

### Environment
- Single-file app (no separate config needed)
- Uses system timezone for time display (converted to ET for consistency)
- Caching enabled (ttl=120-180 seconds) to minimize API calls during session

## Major Functions in app.py

### Utility Functions
- `eastern_time(utc_time)` — Converts UTC time to ET display format
- `normalize_hand_code(code)` — Standardizes player handedness codes (L/R/S)
- `format_pitcher_hand(code)` — Formats pitcher hand for display (LHP/RHP)
- `display_status(status)` — Normalizes game status strings
- `status_color(status)` — Returns color code for game status badge

### Data Fetching Functions (with caching)
- `get_players_info(player_ids)` — Batch fetch player handedness from MLB API
- `load_schedule(game_date)` — Fetch all games for a date; includes pitcher handedness
- `load_lineups(game_pk)` — Fetch away/home lineups for a specific game
- `load_pitcher_stats(player_id)` — Fetch season pitching stats for a pitcher
- `load_savant_pitch_arsenal_data()` — Scrape Savant leaderboard for all pitchers
- `get_savant_arsenal_for_player(player_id)` — Scrape Savant player page for pitch arsenal
- `load_savant_pitcher_data()` — Scrape Savant custom pitcher leaderboard

### Helper Functions
- `_find_json_objects_for_player_page(text, marker)` — Parse JSON from HTML scrape
- `format_number(value, precision, suffix)` — Format stat values with N/A handling

### Main Logic Sections
1. **Header & Sport Selector** — Top navigation, sport selection with fallback
2. **Pitcher Detail Page** — Session state based view when pitcher is clicked
   - Loads all pitcher stats and lineups
   - Renders Pitcher Stats cards (3-column grid)
   - Renders Matchup Read card
   - Renders Opposing Lineup
3. **Slate View** — Date navigation and game grid
   - Loads schedule for selected date
   - Renders 2-column game card layout
   - Handles pitcher click navigation

## File Structure

```
BaseballDashboard/
├── app.py                    # Main Streamlit app (single file)
├── PROJECT_OVERVIEW.md       # This file - project documentation
├── TODO.md                   # Feature tracking and roadmap
└── DEVELOPER_NOTES.md        # Developer guidelines
```

## Known Issues

1. **Baseball Savant Scraping Fragility**
   - HTML parsing depends on specific page structure
   - If Savant changes page layout, pitch arsenal fetching may break
   - Fallback: Shows "Pitch usage data unavailable" with grace

2. **Incomplete Pitch Arsenal Data**
   - Some pitchers may not have full season data on Savant
   - Requires minimum 2 pitch types to display; otherwise shows "N/A"
   - May take 2-3 seconds to load per pitcher (multiple scrapes)

3. **Lineup Timing**
   - Lineups not available until ~30 minutes before game time
   - Shows "Lineup not posted yet" if accessed too early

4. **Sport Selector Placeholder**
   - NBA, NFL, NHL, WNBA show "coming soon" — no data fetching implemented

5. **Session State Persistence**
   - Pitcher detail view stored in session state; lost on browser refresh
   - Date navigation persists within session

6. **Time Zone**
   - All times displayed in ET, but system may use different timezone
   - Conversion works correctly, but display may differ from local time

## Future Roadmap

### Phase 1: Enhanced Matchup Analysis (HIGH PRIORITY)
- [ ] Pitcher vs. Opposing Batter splits (wOBA, K%, etc.)
- [ ] Primary pitch effectiveness stats
- [ ] Left/Right handedness-based pitcher performance
- [ ] Recent form indicators (last 5 starts)

### Phase 2: Multi-Sport Expansion
- [ ] NBA player matchup view
- [ ] NFL QB/Defense analysis
- [ ] NHL goaltender view
- [ ] WNBA player tracking

### Phase 3: Advanced Features
- [ ] Player comparison tool
- [ ] Prop prediction engine
- [ ] Historical stat trends
- [ ] Injury report integration
- [ ] Betting line display
- [ ] Export data (CSV/JSON)

### Phase 4: Performance & UX
- [ ] Database layer (replace API calls)
- [ ] Incremental data loading
- [ ] Mobile-responsive design
- [ ] Dark mode toggle
- [ ] Favorites/watchlist feature

### Phase 5: Analytics & Insights
- [ ] Win probability indicators
- [ ] Implied odds display
- [ ] Custom stat formulas
- [ ] Heatmaps for pitcher performance

## Technical Debt

- Streamlit version constraints (query params removed for compatibility)
- Repeated API calls for player info could be batched more efficiently
- HTML scraping fragile; consider official API partnerships
- No error handling for network failures beyond logging
- Caching TTL could be more granular
