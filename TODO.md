# TODO.md — Feature Tracking & Roadmap

## Completed Features ✅

### Core Functionality
- [x] Multi-sport header with sport selector
- [x] MLB schedule loading and date navigation (← / → / Today / Calendar)
- [x] Game card display (2-column grid layout)
- [x] Team logos and game info (time, venue, status)
- [x] Game status color coding
- [x] Pitcher detail page (session state based)
- [x] Pitcher stats cards (ERA, WHIP, K%, BB%, HR Allowed, IP)
- [x] Pitch arsenal display (fastball, breaking, offspeed %)
- [x] Actual arsenal (detailed pitch type list)
- [x] Opposing lineup display (full game view)
- [x] Lineups in game cards (compact)
- [x] Player handedness detection and display
- [x] Back to Slate navigation

### Data Integration
- [x] MLB Stats API integration (schedule, stats, lineups, player info)
- [x] Baseball Savant pitch arsenal scraping (leaderboard and player pages)
- [x] Timezone conversion (UTC → ET)
- [x] Data caching (120-180 second TTL)
- [x] Error handling with fallback values

### UI/UX Features
- [x] Responsive 2-column game card grid
- [x] Styled stat cards with borders and shadows
- [x] Status badges with dynamic colors
- [x] Team logo display with proper sizing
- [x] Handedness indicators (R/L/S)
- [x] Pitch type categorization (fastball, breaking, offspeed)
- [x] Load time and API call metrics
- [x] Calendar picker for date selection
- [x] Inline pitcher links (button styled as hyperlink)

### Recently Added (This Session)
- [x] Matchup Read section (compact card with key matchup stats)

## In-Progress Features 🚀

None currently — last feature (Matchup Read) stabilized and styled.

## Planned Features 📋

### HIGH PRIORITY (Next Session)
1. **Pitcher vs. Batter Splits**
   - Add another section to pitcher detail page
   - Show how pitcher performs against left/right-handed batters
   - Display wOBA, K%, BB% vs. LHB/RHB
   - Data source: MLB Stats API (splits endpoint)

2. **Matchup Read Enhancement**
   - Add predictive insights (non-statistical)
   - Example: "Pitcher likely to lean fastball early vs. RHB-heavy lineup"
   - Keep factual; no predictions, only observed patterns

3. **Recent Form Indicator**
   - Show pitcher's last 5 starts
   - Display ERA, strikeouts, walks for recent outings
   - Help identify form trends

### MEDIUM PRIORITY
4. **NBA Player Matchup View**
   - Create similar pitcher detail layout for NBA guards/scorers
   - Display season stats, recent form, opposing defense
   - Reuse API integration patterns from MLB

5. **Player Comparison Tool**
   - Compare two pitchers side-by-side
   - Compare stats, pitch arsenal, matchup records
   - Add comparison link to pitcher detail page

6. **Watchlist/Favorites**
   - Save favorite pitchers, players, teams
   - Quick access from slate view
   - Persist using browser local storage

### LOWER PRIORITY (Future Phases)
7. **Prop Prediction Engine**
   - ML model to predict K%, ERA, points scored, etc.
   - Integrate with betting lines
   - Show model confidence and edge

8. **Historical Trends**
   - Chart ERA/WHIP over season
   - Show pitcher performance vs. month
   - Trend direction indicators

9. **Injury Report Integration**
   - Display player health status
   - Show IL players, DTD status
   - Block games with key injured players

10. **Database Layer**
    - Replace API calls with local database
    - Incremental data sync
    - Faster load times
    - Offline capability

11. **Advanced Analytics**
    - Win probability indicator
    - Implied odds display
    - Expected value calculations
    - Custom stat formulas

12. **Export Features**
    - Download matchup data as CSV/JSON
    - Export lineups, stats, matchups
    - Share specific matchup analysis

13. **Mobile Responsive Design**
    - Adapt layout for mobile viewing
    - Touch-friendly pitcher selection
    - Optimized card sizing

14. **Dark Mode**
    - Toggle dark/light theme
    - Persist preference
    - Reduce eye strain for evening use

## Technical Debt 🛠️

### Critical
1. **Baseball Savant HTML Scraping Fragility**
   - Current: Regex/JSON parsing of player page HTML
   - Risk: Page structure changes break everything
   - Solution: Switch to official partnerships or Statsbomb/Trackman API
   - Impact: HIGH (affects pitch arsenal display)

2. **Error Handling Gaps**
   - Network failures logged but not gracefully handled
   - Missing fallback for Savant scrape failures in some cases
   - Solution: Implement circuit breaker pattern, retry logic

### Important
3. **Repeated API Calls for Player Info**
   - Currently fetches handedness individually when not in game feed
   - Could batch more efficiently
   - Solution: Improve caching strategy, pre-fetch common players

4. **Streamlit Version Constraints**
   - Query parameters removed for compatibility with older Streamlit versions
   - Limits future URL-based navigation
   - Solution: Update Streamlit version requirement, test compatibility

5. **No Database Layer**
   - All data fetched on demand
   - Repeated calls during session (though cached)
   - Solution: Add local SQLite or Postgres for off-season prep

### Nice-to-Have
6. **CSS Inline Styling**
   - Heavy use of inline HTML/CSS in Streamlit markdown
   - Difficult to maintain, inconsistent theme
   - Solution: Create Streamlit theme file, centralize styling

7. **Logging Verbosity**
   - Debug logging for all API calls
   - Useful but verbose in production
   - Solution: Add log level configuration

8. **Type Hints**
   - Functions lack type hints
   - Makes code harder to maintain
   - Solution: Add type hints for future refactors

## Next Recommended Steps

### For Next Session (Immediate)
1. **Add Pitcher vs. Batter Splits**
   - Implement in new section on pitcher detail page
   - Use existing `load_pitcher_stats()` function as template
   - Add splits endpoint to MLB Stats API calls
   - Follow existing card styling pattern

2. **Test Savant Scraping Stability**
   - Monitor logs for scrape failures
   - Document common failure patterns
   - Create fallback for unreliable endpoint

3. **Expand Test Coverage**
   - Create test file for helper functions
   - Test edge cases (missing data, invalid inputs)
   - Test with past game dates

### For Future Sessions
4. **Refactor API Layer**
   - Extract API calls into separate `api.py` module
   - Create reusable fetch functions
   - Centralize error handling

5. **Add Configuration**
   - Create `config.py` for constants
   - Move hardcoded values (colors, sizes, TTLs)
   - Allow environment-based configuration

6. **Performance Optimization**
   - Profile app load time
   - Identify bottlenecks (Savant scrape is likely culprit)
   - Consider parallel API calls where safe

7. **Documentation**
   - Keep DEVELOPER_NOTES.md updated
   - Add code comments for complex functions
   - Document API response structures

## Feature Status Summary

| Category | Count | Status |
|----------|-------|--------|
| Completed | 25+ | ✅ Stable |
| In-Progress | 0 | — |
| Planned (High) | 3 | 📋 Next Sprint |
| Planned (Medium) | 3 | 📋 Future |
| Planned (Low) | 8+ | 📋 Backlog |
| Technical Debt | 8 | 🛠️ Monitor |

## Quick Reference: What Changed Recently

### Session: 2026-06-17
- **Added**: Matchup Read section between Pitcher Stats and Opposing Lineup
- **What it shows**: Primary pitch, arsenal lean, opposing lineup, key stats (ERA/WHIP/K%/BB%/HR)
- **Why**: Quick reference for matchup context without clicking into full pitcher detail
- **Status**: Complete, styled as compact bordered card

---

**Last Updated**: 2026-06-17
**Next Review**: After implementing pitcher vs. batter splits
## Dream Feature: Interactive Zone Analysis Grid

### Goal
Create a Baseball Savant-style strike zone visualization with selectable metrics.

### Features
- Pitch Type dropdown
- Metric dropdown

Metrics:
- Pitch %
- Batted Balls
- Hits
- Home Runs
- Barrel/BIP %
- SLG
- Avg EV
- Avg Launch Angle
- Whiff %
- PutAway %

### Display
- 14-zone grid (1-9, 11-14)
- Color heatmap
- Value displayed in each zone
- Optional sample size display

### Future Enhancements
- Batter view
- Pitcher view
- Handedness filters
- Last 7 / 15 / 30 days
- Export zone data
