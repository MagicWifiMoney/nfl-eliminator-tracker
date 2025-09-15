from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import requests
import json
from datetime import datetime, timedelta
import random
import re
import schedule
import threading
import time

app = Flask(__name__)
CORS(app)

class NFLGameTracker:
    def __init__(self):
        self.base_url = "http://site.api.espn.com/apis/site/v2/sports/football/nfl"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        self.current_season = self.get_current_season()
        self.weather_api_key = None  # We'll use free weather service
        self.odds_api_key = "1df7982496664b58ff38d8c96fc8fdf0"  # The Odds API key
        self.odds_cache = None  # Cache odds data to avoid multiple API calls
        self.odds_cache_time = None

        # Team records cache for weekly updates
        self.team_records_cache = {}
        self.team_records_last_updated = None
        self.team_standings_cache = None

        # Daily refresh tracking
        self.last_daily_refresh = None
        self.daily_refresh_hour = 6  # 6 AM default
        
        # NFL Divisions for detecting divisional matchups
        self.nfl_divisions = {
            'AFC East': ['BUF', 'MIA', 'NE', 'NYJ'],
            'AFC North': ['BAL', 'CIN', 'CLE', 'PIT'],
            'AFC South': ['HOU', 'IND', 'JAX', 'TEN'],
            'AFC West': ['DEN', 'KC', 'LV', 'LAC'],
            'NFC East': ['DAL', 'NYG', 'PHI', 'WAS'],
            'NFC North': ['CHI', 'DET', 'GB', 'MIN'],
            'NFC South': ['ATL', 'CAR', 'NO', 'TB'],
            'NFC West': ['ARI', 'LAR', 'SF', 'SEA']
        }
        
        # Stadium coordinates for weather API
        self.venue_coordinates = {
            'Arrowhead Stadium': (39.0489, -94.4839),
            'Lambeau Field': (44.5013, -88.0622),
            'Soldier Field': (41.8623, -87.6167),
            'Ford Field': (42.3400, -83.0456),
            'U.S. Bank Stadium': (44.9738, -93.2581),
            'Lucas Oil Stadium': (39.7601, -86.1639),
            'Heinz Field': (40.4468, -80.0158),
            'M&T Bank Stadium': (39.2780, -76.6227),
            'FirstEnergy Stadium': (41.5061, -81.6995),
            'Paul Brown Stadium': (39.0955, -84.5160),
            'Nissan Stadium': (36.1665, -86.7713),
            'NRG Stadium': (29.6847, -95.4107),
            'TIAA Bank Field': (30.3238, -81.6374),
            'Highmark Stadium': (42.7738, -78.7868),
            'Hard Rock Stadium': (25.9580, -80.2389),
            'Gillette Stadium': (42.0909, -71.2643),
            'MetLife Stadium': (40.8135, -74.0745),
            'Lincoln Financial Field': (39.9008, -75.1675),
            'FedExField': (38.9077, -76.8645),
            'Bank of America Stadium': (35.2258, -80.8528),
            'Mercedes-Benz Stadium': (33.7553, -84.4006),
            'Raymond James Stadium': (27.9759, -82.5033),
            'Mercedes-Benz Superdome': (29.9511, -90.0812),
            'AT&T Stadium': (32.7473, -97.0945),
            'State Farm Stadium': (33.5276, -112.2626),
            'Levi\'s Stadium': (37.4030, -121.9698),
            'SoFi Stadium': (33.9535, -118.3392),
            'Allegiant Stadium': (36.0909, -115.1833),
            'Empower Field at Mile High': (39.7439, -105.0201),
            'Arrowhead Stadium': (39.0489, -94.4839)
        }
    
    def get_current_season(self):
        """Get current NFL season year"""
        now = datetime.now()
        # NFL season runs from September to February of next year
        if now.month >= 9:
            return now.year
        else:
            return now.year - 1
    
    def get_current_week(self):
        """Detect current NFL week based on date"""
        now = datetime.now()
        season_start = datetime(self.current_season, 9, 5)  # Approximate NFL season start
        
        # Adjust for actual season start (first Thursday of September)
        while season_start.weekday() != 3:  # Thursday is day 3
            season_start += timedelta(days=1)
        
        if now < season_start:
            return 1
        
        weeks_since_start = (now - season_start).days // 7 + 1
        return min(max(weeks_since_start, 1), 18)
        
    def get_sample_data(self, week=1):
        """Fallback sample data when ESPN API is unavailable"""
        teams = [
            {"id": 1, "name": "Buffalo Bills", "abbr": "BUF", "record": "10-3", 
             "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/buf.png", 
             "colors": {"primary": "#00338D", "secondary": "#C60C30"}},
            {"id": 2, "name": "Miami Dolphins", "abbr": "MIA", "record": "8-5",
             "logo": "https://a.espncdn.com/i/teamlogos/nfl/500/mia.png", 
             "colors": {"primary": "#008E97", "secondary": "#FC4C02"}},
            {"id": 3, "name": "Kansas City Chiefs", "abbr": "KC", "record": "11-2"},
            {"id": 4, "name": "Cincinnati Bengals", "abbr": "CIN", "record": "7-6"},
            {"id": 5, "name": "Dallas Cowboys", "abbr": "DAL", "record": "9-4"},
            {"id": 6, "name": "Philadelphia Eagles", "abbr": "PHI", "record": "10-3"},
            {"id": 7, "name": "San Francisco 49ers", "abbr": "SF", "record": "8-5"},
            {"id": 8, "name": "Seattle Seahawks", "abbr": "SEA", "record": "6-7"},
            {"id": 9, "name": "Green Bay Packers", "abbr": "GB", "record": "6-7"},
            {"id": 10, "name": "Detroit Lions", "abbr": "DET", "record": "9-4"},
            {"id": 11, "name": "New England Patriots", "abbr": "NE", "record": "3-10"},
            {"id": 12, "name": "New York Jets", "abbr": "NYJ", "record": "4-9"},
            {"id": 13, "name": "Tennessee Titans", "abbr": "TEN", "record": "5-8"},
            {"id": 14, "name": "Jacksonville Jaguars", "abbr": "JAX", "record": "8-5"},
            {"id": 15, "name": "Las Vegas Raiders", "abbr": "LV", "record": "6-7"},
            {"id": 16, "name": "Denver Broncos", "abbr": "DEN", "record": "7-6"}
        ]
        
        sample_games = [
            {
                "id": "401547441",
                "date": "2024-01-07T20:15:00Z",
                "status": "pregame",
                "home_team": teams[2],  # KC
                "away_team": teams[3],  # CIN
                "home_score": 0,
                "away_score": 0,
                "spread": -10.5,
                "favorite": "home",
                "over_under": 47.5,
                "venue": "Arrowhead Stadium",
                "weather": {
                    "temp": 28,
                    "condition": "Snow",
                    "wind": 18,
                    "indoor": False
                }
            },
            {
                "id": "401547442", 
                "date": "2024-01-07T16:30:00Z",
                "status": "pregame",
                "home_team": teams[0],  # BUF
                "away_team": teams[1],  # MIA
                "home_score": 0,
                "away_score": 0,
                "spread": -7.5,
                "favorite": "home", 
                "over_under": 44.5,
                "venue": "Highmark Stadium",
                "weather": {
                    "temp": 22,
                    "condition": "Clear",
                    "wind": 8,
                    "indoor": False
                }
            },
            {
                "id": "401547443",
                "date": "2024-01-07T13:00:00Z", 
                "status": "pregame",
                "home_team": teams[4],  # DAL
                "away_team": teams[5],  # PHI
                "home_score": 0,
                "away_score": 0,
                "spread": -2.5,
                "favorite": "home",
                "over_under": 51.5,
                "venue": "AT&T Stadium",
                "weather": {
                    "temp": 72,
                    "condition": "Indoor",
                    "wind": 0,
                    "indoor": True
                }
            },
            {
                "id": "401547444",
                "date": "2024-01-07T16:30:00Z",
                "status": "pregame", 
                "home_team": teams[6],  # SF
                "away_team": teams[7],  # SEA
                "home_score": 0,
                "away_score": 0,
                "spread": -4.5,
                "favorite": "home",
                "over_under": 42.5,
                "venue": "Levi's Stadium",
                "weather": {
                    "temp": 58,
                    "condition": "Clear",
                    "wind": 5,
                    "indoor": False
                }
            },
            {
                "id": "401547445",
                "date": "2024-01-07T13:00:00Z",
                "status": "pregame",
                "home_team": teams[8],  # GB
                "away_team": teams[9],  # DET
                "home_score": 0,
                "away_score": 0,
                "spread": 3.5,
                "favorite": "away",
                "over_under": 48.5,
                "venue": "Lambeau Field",
                "weather": {
                    "temp": 15,
                    "condition": "Snow",
                    "wind": 22,
                    "indoor": False
                }
            },
            {
                "id": "401547446",
                "date": "2024-01-07T13:00:00Z",
                "status": "pregame",
                "home_team": teams[10],  # NE
                "away_team": teams[11],  # NYJ
                "home_score": 0,
                "away_score": 0,
                "spread": -1.5,
                "favorite": "home",
                "over_under": 37.5,
                "venue": "Gillette Stadium",
                "weather": {
                    "temp": 35,
                    "condition": "Rain",
                    "wind": 12,
                    "indoor": False
                }
            }
        ]
        
        return sample_games
    
    def get_games_for_week(self, week=1):
        """Fetch games for a specific week, with fallback to sample data"""
        print(f"Fetching games for Week {week} of {self.current_season} season...")
        
        # Try multiple ESPN endpoints
        endpoints = [
            f"{self.base_url}/scoreboard?week={week}&seasontype=2&year={self.current_season}",
            f"{self.base_url}/scoreboard?week={week}&seasontype=2",
            f"{self.base_url}/scoreboard?week={week}",
            f"https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/seasons/{self.current_season}/types/2/weeks/{week}/events"
        ]
        
        for url in endpoints:
            try:
                print(f"Trying URL: {url}")
                response = requests.get(url, headers=self.headers, timeout=15)
                
                if response.status_code == 200:
                    data = response.json()
                    print(f"Successfully fetched data from ESPN API")
                    
                    games = self.parse_espn_data(data, week)
                    if games:
                        print(f"Parsed {len(games)} games")
                        # Enhance with betting and weather data
                        games = self.enhance_games_data(games)
                        return games
                    else:
                        print("No games found in ESPN response")
                else:
                    print(f"ESPN API returned status code: {response.status_code}")
                    
            except Exception as e:
                print(f"ESPN API error with {url}: {e}")
                continue
        
        print("All ESPN endpoints failed, using sample data")
        # Fallback to sample data
        return self.get_sample_data(week)
    
    def parse_espn_data(self, data, week=1):
        """Parse ESPN API response into our format"""
        games = []
        
        try:
            events = data.get('events', [])
            
            if not events:
                # Try alternative data structure
                if 'items' in data:
                    events = data['items']
                elif 'competitions' in data:
                    events = data['competitions']
            
            for event in events:
                # Handle different ESPN API response formats
                competition = event.get('competitions', [{}])[0] if 'competitions' in event else event
                
                game = {
                    "id": event.get('id', f"week_{week}_{len(games)}"),
                    "date": event.get('date', competition.get('date', '')),
                    "status": self.parse_game_status(event),
                    "venue": self.parse_venue(competition),
                }
                
                # Get teams
                competitors = competition.get('competitors', [])
                
                if len(competitors) >= 2:
                    for competitor in competitors:
                        team_data = competitor.get('team', {})
                        
                        team_info = {
                            "id": team_data.get('id', ''),
                            "name": team_data.get('displayName', team_data.get('name', '')),
                            "abbr": team_data.get('abbreviation', ''),
                            "record": self.enhanced_parse_team_record(competitor),
                            "score": int(competitor.get('score', 0)),
                            "logo": self.get_team_logo_url(team_data.get('abbreviation', '')),
                            "colors": self.get_team_colors(team_data.get('abbreviation', ''))
                        }
                        
                        if competitor.get('homeAway') == 'home':
                            game['home_team'] = team_info
                            game['home_score'] = team_info['score']
                        else:
                            game['away_team'] = team_info  
                            game['away_score'] = team_info['score']
                    
                    # Only add games with both teams
                    if 'home_team' in game and 'away_team' in game:
                        games.append(game)
                
        except Exception as e:
            print(f"Error parsing ESPN data: {e}")
            import traceback
            traceback.print_exc()
            return []
            
        return games
    
    def parse_game_status(self, event):
        """Extract game status from ESPN event data"""
        status = event.get('status', {})
        
        if isinstance(status, dict):
            status_type = status.get('type', {})
            if isinstance(status_type, dict):
                name = status_type.get('name', 'pregame').lower()
            else:
                name = str(status_type).lower()
        else:
            name = str(status).lower()
        
        # Normalize status names
        if 'final' in name or 'end' in name:
            return 'final'
        elif 'progress' in name or 'live' in name or 'active' in name:
            return 'live'
        else:
            return 'pregame'
    
    def parse_venue(self, competition):
        """Extract venue information"""
        venue = competition.get('venue', {})
        if isinstance(venue, dict):
            return venue.get('fullName', venue.get('name', ''))
        return str(venue) if venue else ''
    
    def parse_team_record(self, competitor):
        """Extract team record from competitor data"""
        records = competitor.get('records', [])
        if records and len(records) > 0:
            return records[0].get('displayValue', '0-0')
        
        # Try alternative record location
        record = competitor.get('record', {})
        if isinstance(record, list) and record:
            return record[0].get('displayValue', '0-0')
        elif isinstance(record, dict):
            return record.get('displayValue', '0-0')
        
        return '0-0'
    
    def enhance_games_data(self, games):
        """Add betting lines, weather data, and injury reports to games"""
        # Fetch odds data once for all games (more efficient)
        self.refresh_odds_cache()
        
        for game in games:
            # Add betting data using cached odds
            game.update(self.get_betting_data(game))
            # Add weather data
            game['weather'] = self.get_weather_data(game)
            # Add injury data
            game['injuries'] = self.get_injury_data_for_game(game)
            # Add team analytics
            game['analytics'] = self.get_team_analytics_for_game(game)
            # Add relevant news
            game['news'] = self.get_game_news(game)
            # Add win probabilities
            game['probabilities'] = self.calculate_game_probabilities(game)
            # Add advanced research metrics
            game['advanced_metrics'] = {
                'home_team': self.calculate_advanced_team_metrics(game.get('home_team', {}).get('abbr', ''), 1),
                'away_team': self.calculate_advanced_team_metrics(game.get('away_team', {}).get('abbr', ''), 1)
            }
            # Add divisional matchup detection
            game['divisional'] = self.is_divisional_game(game)
        
        return games
    
    def is_divisional_game(self, game):
        """Check if a game is between division rivals"""
        home_abbr = game.get('home_team', {}).get('abbr', '')
        away_abbr = game.get('away_team', {}).get('abbr', '')
        
        if not home_abbr or not away_abbr:
            return False
            
        # Check each division
        for division, teams in self.nfl_divisions.items():
            if home_abbr in teams and away_abbr in teams:
                return True
                
        return False
    
    def refresh_odds_cache(self):
        """Refresh odds cache if needed (every 10 minutes)"""
        now = datetime.now()
        
        if (self.odds_cache_time is None or 
            (now - self.odds_cache_time).total_seconds() > 600):  # 10 minutes
            
            try:
                print("Fetching real betting odds from The Odds API...")
                url = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds"
                params = {
                    'api_key': self.odds_api_key,
                    'regions': 'us',
                    'markets': 'h2h,spreads,totals',  # h2h = moneyline
                    'oddsFormat': 'american'
                }
                
                response = requests.get(url, params=params, timeout=10)
                
                if response.status_code == 200:
                    self.odds_cache = response.json()
                    self.odds_cache_time = now
                    print(f"Successfully cached {len(self.odds_cache)} games with real betting odds")
                else:
                    print(f"Odds API returned status code: {response.status_code}")
                    if response.status_code == 401:
                        print("Invalid API key for The Odds API")
                    elif response.status_code == 429:
                        print("Rate limit exceeded for The Odds API")
                        
            except Exception as e:
                print(f"Error fetching odds cache: {e}")
    
    def get_betting_data(self, game):
        """Get betting lines for a game - try real odds API first"""
        # Try to get real betting odds
        real_odds = self.get_real_betting_odds_for_game(game)
        if real_odds:
            return real_odds
        
        # Fallback to enhanced mock data
        return self.get_mock_betting_data(game)
    
    def get_real_betting_odds_for_game(self, game):
        """Get real betting odds from cached data"""
        if not self.odds_cache:
            return None
        
        try:
            # Match this game to cached odds data
            home_team = game.get('home_team', {}).get('name', '')
            away_team = game.get('away_team', {}).get('name', '')
            
            for odds_game in self.odds_cache:
                if (self.teams_match(odds_game.get('home_team', ''), home_team) and 
                    self.teams_match(odds_game.get('away_team', ''), away_team)):
                    
                    return self.parse_odds_data(odds_game)
                    
        except Exception as e:
            print(f"Error matching game to cached odds: {e}")
        
        return None
    
    def teams_match(self, api_team, game_team):
        """Check if team names match between APIs"""
        if not api_team or not game_team:
            return False
        
        # Normalize team names for matching
        api_team_clean = api_team.lower().replace(' ', '')
        game_team_clean = game_team.lower().replace(' ', '')
        
        # Handle common variations
        name_variations = {
            'losangelesrams': ['rams', 'larams'],
            'losangeleschargers': ['chargers', 'lachargers'],
            'newyorkgiants': ['giants', 'nygiants'],
            'newyorkjets': ['jets', 'nyjets'],
            'newenglandpatriots': ['patriots', 'newengland'],
            'greenbaypackers': ['packers', 'greenbay'],
            'tampabaybucs': ['buccaneers', 'tampabay', 'bucs'],
            'kansascitychiefs': ['chiefs', 'kansascity'],
            'sanfrancisco49ers': ['49ers', 'sanfrancisco'],
            'lasvegasraiders': ['raiders', 'lasvegas', 'oaklandraiders']
        }
        
        # Direct match
        if api_team_clean == game_team_clean:
            return True
        
        # Check variations
        for canonical, variations in name_variations.items():
            if api_team_clean == canonical and any(var in game_team_clean for var in variations):
                return True
            if game_team_clean == canonical and any(var in api_team_clean for var in variations):
                return True
        
        # Check if one contains the other
        return api_team_clean in game_team_clean or game_team_clean in api_team_clean
    
    def parse_odds_data(self, odds_game):
        """Parse odds data from The Odds API"""
        spread = 0
        over_under = 0
        home_moneyline = None
        away_moneyline = None
        
        if 'bookmakers' in odds_game and odds_game['bookmakers']:
            bookmaker = odds_game['bookmakers'][0]  # Use first bookmaker (DraftKings, etc.)
            
            for market in bookmaker.get('markets', []):
                if market['key'] == 'h2h':  # Moneyline market
                    for outcome in market.get('outcomes', []):
                        if outcome['name'] == odds_game.get('home_team'):
                            home_moneyline = outcome.get('price')
                        elif outcome['name'] == odds_game.get('away_team'):
                            away_moneyline = outcome.get('price')
                
                elif market['key'] == 'spreads':
                    # Find the spread
                    for outcome in market.get('outcomes', []):
                        if 'point' in outcome:
                            point = outcome['point']
                            if point < 0:  # This is the favorite
                                spread = point
                                break
                
                elif market['key'] == 'totals':
                    # Get the over/under total
                    for outcome in market.get('outcomes', []):
                        if outcome['name'] == 'Over' and 'point' in outcome:
                            over_under = outcome['point']
                            break
        
        print(f"Real odds found: Spread {spread}, O/U {over_under}, Moneylines: {home_moneyline}/{away_moneyline}")
        
        return {
            'spread': spread,
            'favorite': 'home' if spread < 0 else 'away',
            'over_under': over_under or round(random.uniform(40, 55) * 2) / 2,
            'home_moneyline': home_moneyline,
            'away_moneyline': away_moneyline,
            'betting': {
                'home_moneyline': home_moneyline,
                'away_moneyline': away_moneyline
            }
        }
    
    def get_mock_betting_data(self, game):
        """Fallback mock betting data based on team strength"""
        home_team = game.get('home_team', {}).get('abbr', '')
        away_team = game.get('away_team', {}).get('abbr', '')
        
        # Strong teams (mock strength ratings)
        strong_teams = ['BUF', 'KC', 'PHI', 'SF', 'BAL', 'CIN', 'DAL', 'MIA', 'DET']
        weak_teams = ['HOU', 'CAR', 'ARI', 'NYG', 'CHI', 'WAS', 'DEN', 'NYJ']
        
        spread = 0
        if home_team in strong_teams and away_team in weak_teams:
            spread = round(random.uniform(-10, -6) * 2) / 2
        elif home_team in weak_teams and away_team in strong_teams:
            spread = round(random.uniform(3, 7) * 2) / 2
        elif home_team in strong_teams and away_team not in weak_teams:
            spread = round(random.uniform(-6, -2) * 2) / 2
        elif away_team in strong_teams and home_team not in weak_teams:
            spread = round(random.uniform(1, 4) * 2) / 2
        else:
            spread = round(random.uniform(-3, 3) * 2) / 2
        
        # Convert spread to approximate moneyline odds
        if spread < 0:  # Home team favored
            home_moneyline = int(-110 - (abs(spread) * 15))  # Rough approximation
            away_moneyline = int(110 + (abs(spread) * 15))
        elif spread > 0:  # Away team favored  
            away_moneyline = int(-110 - (abs(spread) * 15))
            home_moneyline = int(110 + (abs(spread) * 15))
        else:  # Pick'em
            home_moneyline = -105
            away_moneyline = -105
        
        return {
            'spread': spread,
            'favorite': 'home' if spread < 0 else 'away',
            'over_under': round(random.uniform(40, 55) * 2) / 2,
            'home_moneyline': home_moneyline,
            'away_moneyline': away_moneyline,
            'betting': {
                'home_moneyline': home_moneyline,
                'away_moneyline': away_moneyline
            }
        }
    
    def get_weather_data(self, game):
        """Get weather data for game venue"""
        venue = game.get('venue', '').lower()
        
        # Indoor venues
        indoor_venues = [
            'at&t stadium', 'mercedes-benz superdome', 'ford field', 'lucas oil stadium',
            'u.s. bank stadium', 'state farm stadium', 'mercedes-benz stadium', 
            'allegiant stadium', 'sofi stadium', 'dome', 'indoor'
        ]
        
        is_indoor = any(indoor in venue for indoor in indoor_venues)
        
        if is_indoor:
            return {
                "temp": 72,
                "condition": "Indoor",
                "wind": 0,
                "indoor": True
            }
        
        # Try to get real weather data
        real_weather = self.get_real_weather_for_venue(game.get('venue', ''))
        if real_weather:
            return real_weather
        
        # Fallback: Generate realistic outdoor weather based on season/location
        month = datetime.now().month
        
        if month in [12, 1, 2]:  # Winter
            temp_range = (15, 45)
            conditions = ["Clear", "Cloudy", "Snow", "Snow"]  # More snow
        elif month in [3, 4, 11]:  # Fall/Spring
            temp_range = (35, 65)
            conditions = ["Clear", "Cloudy", "Rain", "Clear"]
        else:  # Summer
            temp_range = (65, 85)
            conditions = ["Clear", "Clear", "Cloudy", "Rain"]
        
        return {
            "temp": random.randint(*temp_range),
            "condition": random.choice(conditions),
            "wind": random.randint(0, 20),
            "indoor": False
        }
    
    def get_real_weather_for_venue(self, venue_name):
        """Get real weather data for a venue using free weather service"""
        if not venue_name or venue_name.lower() in ['', 'unknown']:
            return None
            
        # Find coordinates for this venue
        coordinates = None
        for venue_key, coords in self.venue_coordinates.items():
            if venue_key.lower() in venue_name.lower() or venue_name.lower() in venue_key.lower():
                coordinates = coords
                break
        
        if not coordinates:
            return None
        
        lat, lon = coordinates
        
        try:
            # Using wttr.in - free weather API that doesn't require API key
            url = f"https://wttr.in/{lat},{lon}?format=j1"
            response = requests.get(url, timeout=5, headers=self.headers)
            
            if response.status_code == 200:
                data = response.json()
                current = data.get('current_condition', [{}])[0]
                
                temp_f = int(float(current.get('temp_F', 32)))
                condition = current.get('weatherDesc', [{}])[0].get('value', 'Clear')
                wind_mph = int(float(current.get('windspeedMiles', 0)))
                
                # Normalize condition names
                condition_map = {
                    'sunny': 'Clear',
                    'clear': 'Clear', 
                    'partly cloudy': 'Cloudy',
                    'cloudy': 'Cloudy',
                    'overcast': 'Cloudy',
                    'light rain': 'Rain',
                    'moderate rain': 'Rain',
                    'heavy rain': 'Rain',
                    'light snow': 'Snow',
                    'moderate snow': 'Snow',
                    'heavy snow': 'Snow',
                }
                
                normalized_condition = condition_map.get(condition.lower(), condition)
                
                print(f"Real weather for {venue_name}: {temp_f}°F, {normalized_condition}, {wind_mph}mph wind")
                
                return {
                    "temp": temp_f,
                    "condition": normalized_condition,
                    "wind": wind_mph,
                    "indoor": False
                }
                
        except Exception as e:
            print(f"Weather API failed for {venue_name}: {e}")
        
        return None
    
    def calculate_elo_ratings(self, team_abbr):
        """Calculate simplified Elo-style ratings for teams"""
        # Base ratings for different team tiers (simplified system)
        elite_teams = {
            'KC': 1650, 'BUF': 1620, 'PHI': 1600, 'SF': 1590, 'BAL': 1580, 
            'CIN': 1570, 'DAL': 1560, 'MIA': 1550
        }
        strong_teams = {
            'LAC': 1540, 'MIN': 1530, 'NYJ': 1520, 'JAX': 1510, 'TEN': 1500,
            'CLE': 1490, 'LV': 1480, 'NE': 1470
        }
        average_teams = {
            'PIT': 1460, 'IND': 1450, 'NO': 1440, 'TB': 1430, 'ATL': 1420,
            'GB': 1410, 'DET': 1400, 'SEA': 1390
        }
        weak_teams = {
            'LAR': 1380, 'ARI': 1370, 'WAS': 1360, 'NYG': 1350, 'CHI': 1340,
            'CAR': 1330, 'DEN': 1320, 'HOU': 1310
        }
        
        # Get base rating
        if team_abbr in elite_teams:
            base_rating = elite_teams[team_abbr]
            tier = 'Elite'
        elif team_abbr in strong_teams:
            base_rating = strong_teams[team_abbr]
            tier = 'Strong'
        elif team_abbr in average_teams:
            base_rating = average_teams[team_abbr]
            tier = 'Average'
        elif team_abbr in weak_teams:
            base_rating = weak_teams[team_abbr]
            tier = 'Weak'
        else:
            base_rating = 1400  # Default average
            tier = 'Average'
        
        # Add some randomization to simulate season variance
        variance = random.randint(-50, 50)
        current_rating = base_rating + variance
        
        return {
            'rating': current_rating,
            'tier': tier,
            'base_rating': base_rating,
            'variance': variance
        }
    
    def calculate_strength_of_schedule(self, team_abbr, week):
        """Calculate strength of schedule metrics"""
        # Simulate opponents faced and remaining
        played_opponents = random.randint(max(1, week-1), week)
        remaining_opponents = 18 - week
        
        # Generate realistic SOS scores
        played_sos = round(random.uniform(0.35, 0.65), 3)  # Historical range
        remaining_sos = round(random.uniform(0.35, 0.65), 3)
        season_sos = round((played_sos + remaining_sos) / 2, 3)
        
        return {
            'season_sos': season_sos,
            'played_sos': played_sos,
            'remaining_sos': remaining_sos,
            'played_games': played_opponents,
            'remaining_games': remaining_opponents,
            'sos_rank': random.randint(1, 32),  # Rank among all teams
            'difficulty': 'Hard' if season_sos > 0.55 else 'Medium' if season_sos > 0.45 else 'Easy'
        }
    
    def calculate_advanced_team_metrics(self, team_abbr, week=1):
        """Calculate comprehensive advanced metrics for a team"""
        elo_data = self.calculate_elo_ratings(team_abbr)
        sos_data = self.calculate_strength_of_schedule(team_abbr, week)
        
        # Calculate additional metrics
        rest_advantage = random.choice([0, 3, 6, 10])  # Days of rest advantage
        travel_distance = random.randint(0, 2500)  # Miles traveled
        
        # Home/Road splits
        home_record = f"{random.randint(3, 8)}-{random.randint(0, 5)}"
        road_record = f"{random.randint(2, 7)}-{random.randint(1, 6)}"
        
        # Recent trends
        last_5_record = f"{random.randint(2, 5)}-{random.randint(0, 3)}"
        
        return {
            'elo': elo_data,
            'strength_of_schedule': sos_data,
            'rest_advantage': rest_advantage,
            'travel_distance': travel_distance,
            'home_record': home_record,
            'road_record': road_record,
            'last_5_games': last_5_record,
            'division_record': f"{random.randint(1, 5)}-{random.randint(0, 4)}",
            'vs_winning_teams': f"{random.randint(1, 4)}-{random.randint(2, 6)}",
            'in_primetime': f"{random.randint(0, 2)}-{random.randint(0, 2)}"
        }
    
    def calculate_implied_probability(self, odds):
        """Calculate implied probability from American odds"""
        if odds is None or odds == 0:
            return 50.0  # Default to 50/50 if no odds
        
        if odds < 0:  # Negative odds (favorite)
            return abs(odds) / (abs(odds) + 100) * 100
        else:  # Positive odds (underdog)
            return 100 / (odds + 100) * 100
    
    def spread_to_moneyline_probability(self, spread):
        """Convert point spread to approximate moneyline probability"""
        if spread == 0:
            return 50.0
        
        # Historical data conversion: each point is roughly worth about 2.5% probability
        # This is an approximation based on NFL historical data
        probability_adjustment = abs(spread) * 2.5
        
        if spread < 0:  # Home team favored
            return min(50 + probability_adjustment, 85)  # Cap at 85%
        else:  # Away team favored  
            return max(50 - probability_adjustment, 15)  # Floor at 15%
    
    def calculate_game_probabilities(self, game):
        """Calculate comprehensive win probabilities for both teams"""
        betting_data = game.get('betting', {})
        spread = betting_data.get('spread', 0)
        
        # Try to get moneyline odds first (more accurate)
        home_moneyline = betting_data.get('home_moneyline')
        away_moneyline = betting_data.get('away_moneyline')
        
        if home_moneyline and away_moneyline:
            # Calculate from actual moneyline odds
            home_probability = self.calculate_implied_probability(home_moneyline)
            away_probability = self.calculate_implied_probability(away_moneyline)
            
            # Remove vig (bookmaker's edge) by normalizing
            total_prob = home_probability + away_probability
            home_probability = (home_probability / total_prob) * 100
            away_probability = (away_probability / total_prob) * 100
            
        else:
            # Fall back to spread-based probability calculation
            if game.get('favorite') == 'home':
                home_probability = self.spread_to_moneyline_probability(-abs(spread))
                away_probability = 100 - home_probability
            else:
                away_probability = self.spread_to_moneyline_probability(-abs(spread))
                home_probability = 100 - away_probability
        
        return {
            'home_probability': round(home_probability, 1),
            'away_probability': round(away_probability, 1),
            'confidence_level': self.determine_probability_confidence(max(home_probability, away_probability)),
            'method': 'moneyline' if (home_moneyline and away_moneyline) else 'spread'
        }
    
    def determine_probability_confidence(self, max_probability):
        """Determine confidence level based on probability"""
        if max_probability >= 75:
            return 'very_high'
        elif max_probability >= 65:
            return 'high'
        elif max_probability >= 55:
            return 'medium'
        else:
            return 'low'
    
    def get_eliminator_recommendation(self, game):
        """Generate eliminator pool recommendation based on game data"""
        # Get advanced analytics first
        analytics = self.get_advanced_eliminator_analysis(game)
        
        # Determine recommended team
        if game.get('favorite') == 'home':
            recommended_team = game.get('home_team', {}).get('abbr')
        else:
            recommended_team = game.get('away_team', {}).get('abbr')
        
        return {
            "recommended_team": recommended_team,
            "confidence": analytics['confidence'],
            "reasons": analytics['reasons'],
            "warnings": analytics['warnings'],
            "safety_score": analytics['safety_score'],
            "risk_factors": analytics['risk_factors'],
            "value_score": analytics['value_score']
        }
    
    def get_advanced_eliminator_analysis(self, game):
        """Enhanced eliminator pool analysis with probability-based multi-factor confidence scoring"""
        spread = abs(game.get('spread', 0))
        weather = game.get('weather', {})
        home_team = game.get('home_team', {})
        away_team = game.get('away_team', {})
        probabilities = game.get('probabilities', {})
        injuries = game.get('injuries', {})
        analytics = game.get('analytics', {})
        
        analysis = {
            'safety_score': 0,      # 0-100, higher = safer pick
            'value_score': 0,       # 0-100, higher = better value
            'confidence': 'low',    # low, medium, high, very_high
            'probability_score': 0, # 0-100, based on win probability
            'reasons': [],
            'warnings': [],
            'risk_factors': []
        }
        
        # Get the favorite team's probability
        if game.get('favorite') == 'home':
            favorite_probability = probabilities.get('home_probability', 50)
            underdog_probability = probabilities.get('away_probability', 50)
        else:
            favorite_probability = probabilities.get('away_probability', 50)
            underdog_probability = probabilities.get('home_probability', 50)
        
        # 1. PROBABILITY SAFETY SCORING (40% weight - PRIMARY FACTOR)
        probability_safety = self.calculate_probability_safety(favorite_probability, probabilities.get('method'))
        analysis['safety_score'] += probability_safety['score'] * 0.4
        analysis['probability_score'] = probability_safety['score']
        analysis['reasons'].extend(probability_safety['reasons'])
        analysis['risk_factors'].extend(probability_safety['risks'])
        
        # 2. SPREAD SAFETY SCORING (25% weight)
        spread_safety = self.calculate_spread_safety(spread)
        analysis['safety_score'] += spread_safety['score'] * 0.25
        analysis['reasons'].extend(spread_safety['reasons'])
        analysis['risk_factors'].extend(spread_safety['risks'])
        
        # 3. TEAM STRENGTH SCORING (20% weight)
        team_safety = self.calculate_team_strength_safety(home_team, away_team, game.get('favorite'), analytics)
        analysis['safety_score'] += team_safety['score'] * 0.2
        analysis['reasons'].extend(team_safety['reasons'])
        analysis['risk_factors'].extend(team_safety['risks'])
        
        # 4. WEATHER & INJURY ADJUSTMENTS (15% weight)
        external_safety = self.calculate_external_factors_safety(weather, injuries)
        analysis['safety_score'] += external_safety['score'] * 0.15
        analysis['reasons'].extend(external_safety['reasons'])
        analysis['risk_factors'].extend(external_safety['risks'])
        
        # 4. VALUE SCORING (separate metric)
        analysis['value_score'] = self.calculate_value_score(game, analysis['safety_score'])
        
        # 5. DETERMINE CONFIDENCE LEVEL (updated to use probability)
        analysis['confidence'] = self.determine_confidence_level_enhanced(
            analysis['safety_score'], 
            analysis['probability_score'], 
            favorite_probability
        )
        
        # 6. ADD WARNINGS FOR HIGH-RISK FACTORS
        if favorite_probability < 60:
            analysis['warnings'].append("LOW PROBABILITY: Consider higher confidence picks")
        elif analysis['safety_score'] < 50:
            analysis['warnings'].append("MODERATE RISK: Multiple risk factors present")
        
        if len(analysis['risk_factors']) >= 3:
            analysis['warnings'].append("HIGH RISK: Multiple risk factors identified")
        
        return analysis
    
    def calculate_probability_safety(self, favorite_probability, method):
        """Calculate safety score based on win probability"""
        result = {'score': 0, 'reasons': [], 'risks': []}
        
        # Convert probability to safety score (0-100)
        if favorite_probability >= 85:
            result['score'] = 95
            result['reasons'].append(f"Extremely high win probability ({favorite_probability}%)")
        elif favorite_probability >= 75:
            result['score'] = 85
            result['reasons'].append(f"Very high win probability ({favorite_probability}%)")
        elif favorite_probability >= 70:
            result['score'] = 75
            result['reasons'].append(f"High win probability ({favorite_probability}%)")
        elif favorite_probability >= 65:
            result['score'] = 65
            result['reasons'].append(f"Above average win probability ({favorite_probability}%)")
        elif favorite_probability >= 60:
            result['score'] = 55
            result['reasons'].append(f"Moderate win probability ({favorite_probability}%)")
        elif favorite_probability >= 55:
            result['score'] = 45
            result['reasons'].append(f"Slight favorite ({favorite_probability}%)")
            result['risks'].append("Low probability margin")
        else:
            result['score'] = 25
            result['reasons'].append(f"Low win probability ({favorite_probability}%)")
            result['risks'].append("High upset potential")
        
        # Add method context
        if method == 'moneyline':
            result['reasons'].append("Based on real moneyline odds")
        else:
            result['reasons'].append("Estimated from point spread")
            result['risks'].append("Probability estimated from spread (less precise)")
        
        return result
    
    def calculate_spread_safety(self, spread):
        """Calculate safety score based on point spread"""
        result = {'score': 0, 'reasons': [], 'risks': []}
        
        if spread >= 10:
            result['score'] = 40
            result['reasons'].append(f"Large spread ({spread} points) - very safe")
        elif spread >= 7:
            result['score'] = 30
            result['reasons'].append(f"Solid favorite ({spread} points) - safe")
        elif spread >= 4:
            result['score'] = 20
            result['reasons'].append(f"Moderate spread ({spread} points) - somewhat safe")
        elif spread >= 2:
            result['score'] = 10
            result['reasons'].append(f"Close spread ({spread} points) - risky")
            result['risks'].append("Close spread increases upset potential")
        else:
            result['score'] = 5
            result['reasons'].append(f"Very close spread ({spread} points) - very risky")
            result['risks'].append("Very close spread - high upset risk")
        
        return result
    
    def calculate_weather_safety(self, weather):
        """Calculate safety score based on weather conditions"""
        result = {'score': 0, 'reasons': [], 'risks': []}
        
        if weather.get('indoor', False):
            result['score'] = 30
            result['reasons'].append("Indoor game - no weather impact")
        else:
            condition = weather.get('condition', 'Clear')
            wind = weather.get('wind', 0)
            temp = weather.get('temp', 70)
            
            # Base weather score
            if condition in ['Clear', 'Cloudy']:
                result['score'] = 25
                result['reasons'].append(f"Good weather conditions ({condition})")
            elif condition == 'Rain':
                result['score'] = 15
                result['reasons'].append(f"Rain expected - affects passing game")
                result['risks'].append("Rain can cause upsets and turnovers")
            elif condition == 'Snow':
                result['score'] = 10
                result['reasons'].append(f"Snow expected - unpredictable conditions")
                result['risks'].append("Snow creates high variance - anything can happen")
            
            # Wind impact
            if wind > 20:
                result['score'] -= 10
                result['risks'].append(f"High winds ({wind} mph) - affects kicking and passing")
            elif wind > 15:
                result['score'] -= 5
                result['risks'].append(f"Moderate winds ({wind} mph) - slight impact")
            
            # Temperature impact
            if temp < 20:
                result['score'] -= 5
                result['risks'].append(f"Very cold ({temp}°F) - affects ball handling")
            elif temp > 90:
                result['score'] -= 3
                result['risks'].append(f"Very hot ({temp}°F) - affects player endurance")
        
        return result
    
    def calculate_team_strength_safety(self, home_team, away_team, favorite, analytics=None):
        """Calculate safety score based on team strength"""
        result = {'score': 0, 'reasons': [], 'risks': []}
        
        # Parse team records
        home_record = self.parse_team_record(home_team.get('record', '0-0'))
        away_record = self.parse_team_record(away_team.get('record', '0-0'))
        
        # Determine which team is the favorite
        if favorite == 'home':
            fav_record = home_record
            underdog_record = away_record
            fav_team = home_team.get('abbr', '')
        else:
            fav_record = away_record
            underdog_record = home_record
            fav_team = away_team.get('abbr', '')
        
        # Calculate strength difference
        fav_strength = fav_record['wins'] - fav_record['losses']
        underdog_strength = underdog_record['wins'] - underdog_record['losses']
        strength_diff = fav_strength - underdog_strength
        
        # Score based on strength difference
        if strength_diff >= 6:
            result['score'] = 30
            result['reasons'].append(f"Strong favorite ({fav_team}: {fav_record['wins']}-{fav_record['losses']})")
        elif strength_diff >= 3:
            result['score'] = 25
            result['reasons'].append(f"Solid favorite ({fav_team}: {fav_record['wins']}-{fav_record['losses']})")
        elif strength_diff >= 1:
            result['score'] = 15
            result['reasons'].append(f"Moderate favorite ({fav_team}: {fav_record['wins']}-{fav_record['losses']})")
        elif strength_diff == 0:
            result['score'] = 10
            result['reasons'].append("Evenly matched teams")
            result['risks'].append("Teams have similar records - unpredictable")
        else:
            result['score'] = 5
            result['reasons'].append("Underdog favored by record")
            result['risks'].append("Underdog has better record - high upset risk")
        
        # Additional risk factors
        if fav_record['wins'] < 5:
            result['risks'].append(f"Favorite has losing record ({fav_record['wins']}-{fav_record['losses']})")
        if underdog_record['wins'] >= 8:
            result['risks'].append(f"Strong underdog ({underdog_record['wins']}-{underdog_record['losses']})")
        
        return result
    
    def calculate_value_score(self, game, safety_score):
        """Calculate value score for the pick (0-100)"""
        spread = abs(game.get('spread', 0))
        over_under = game.get('over_under', 45)
        
        # Base value on spread size vs safety
        if spread >= 10 and safety_score >= 80:
            return 95  # High value - safe and large spread
        elif spread >= 7 and safety_score >= 70:
            return 85  # Good value - safe with decent spread
        elif spread >= 4 and safety_score >= 60:
            return 70  # Moderate value
        elif spread >= 2 and safety_score >= 50:
            return 55  # Low value - risky
        else:
            return 30  # Very low value - high risk
        
    def calculate_external_factors_safety(self, weather, injuries):
        """Calculate safety score for weather and injury factors combined"""
        result = {'score': 0, 'reasons': [], 'risks': []}
        
        # Weather factor
        weather_score = 0
        if weather.get('indoor', False):
            weather_score = 100
            result['reasons'].append("Indoor game - no weather impact")
        else:
            condition = weather.get('condition', 'Clear')
            wind = weather.get('wind', 0)
            
            if condition in ['Clear', 'Cloudy']:
                weather_score = 85
                result['reasons'].append(f"Good weather conditions ({condition})")
            elif condition == 'Rain':
                weather_score = 60
                result['reasons'].append(f"Rain expected - affects game flow")
                result['risks'].append("Rain increases turnover potential")
            elif condition == 'Snow':
                weather_score = 40
                result['reasons'].append(f"Snow expected - unpredictable conditions")
                result['risks'].append("Snow creates high variance scenarios")
            
            # Wind adjustments
            if wind > 20:
                weather_score -= 30
                result['risks'].append(f"High winds ({wind} mph) - major impact on kicking")
            elif wind > 15:
                weather_score -= 15
                result['risks'].append(f"Moderate winds ({wind} mph) - affects passing")
        
        # Injury factor
        injury_score = 100
        impact_score = injuries.get('impact_score', 0)
        
        if impact_score >= 7:
            injury_score = 60
            result['risks'].append("High injury impact - multiple key players out")
        elif impact_score >= 4:
            injury_score = 75
            result['risks'].append("Moderate injury impact - some key players affected")
        elif impact_score >= 2:
            injury_score = 85
            result['reasons'].append("Minor injury concerns")
        else:
            result['reasons'].append("No significant injury concerns")
        
        # Combined score (weighted average)
        result['score'] = (weather_score * 0.7) + (injury_score * 0.3)
        
        return result
    
    def determine_confidence_level_enhanced(self, safety_score, probability_score, favorite_probability):
        """Enhanced confidence level determination using probability data"""
        # Primary factor: win probability
        if favorite_probability >= 80 and safety_score >= 75:
            return 'very_high'
        elif favorite_probability >= 75 and safety_score >= 70:
            return 'very_high'
        elif favorite_probability >= 70 and safety_score >= 65:
            return 'high'
        elif favorite_probability >= 65 and safety_score >= 60:
            return 'high'
        elif favorite_probability >= 60 and safety_score >= 50:
            return 'medium'
        elif favorite_probability >= 55 and safety_score >= 45:
            return 'medium'
        else:
            return 'low'
    
    def determine_confidence_level(self, safety_score, value_score):
        """Determine overall confidence level (legacy method)"""
        if safety_score >= 80 and value_score >= 80:
            return 'high'
        elif safety_score >= 60 and value_score >= 60:
            return 'medium'
        else:
            return 'low'
    
    def parse_team_record(self, record_str):
        """Parse team record string into wins/losses"""
        try:
            if '-' in record_str:
                wins, losses = record_str.split('-')
                return {'wins': int(wins), 'losses': int(losses)}
        except:
            pass
        return {'wins': 0, 'losses': 0}
    
    def get_team_logo_url(self, team_abbr):
        """Get ESPN CDN logo URL for team"""
        if not team_abbr:
            return None
        
        # ESPN CDN pattern for team logos
        return f"https://a.espncdn.com/i/teamlogos/nfl/500/{team_abbr.lower()}.png"
    
    def get_team_colors(self, team_abbr):
        """Get team primary and secondary colors"""
        team_colors = {
            'ARI': {'primary': '#97233F', 'secondary': '#FFB612'},
            'ATL': {'primary': '#A71930', 'secondary': '#000000'},
            'BAL': {'primary': '#241773', 'secondary': '#9E7C0C'},
            'BUF': {'primary': '#00338D', 'secondary': '#C60C30'},
            'CAR': {'primary': '#0085CA', 'secondary': '#101820'},
            'CHI': {'primary': '#0B162A', 'secondary': '#C83803'},
            'CIN': {'primary': '#FB4F14', 'secondary': '#000000'},
            'CLE': {'primary': '#311D00', 'secondary': '#FF3C00'},
            'DAL': {'primary': '#003594', 'secondary': '#869397'},
            'DEN': {'primary': '#FB4F14', 'secondary': '#002244'},
            'DET': {'primary': '#0076B6', 'secondary': '#B0B7BC'},
            'GB': {'primary': '#203731', 'secondary': '#FFB612'},
            'HOU': {'primary': '#03202F', 'secondary': '#A71930'},
            'IND': {'primary': '#002C5F', 'secondary': '#A2AAAD'},
            'JAX': {'primary': '#101820', 'secondary': '#D7A22A'},
            'KC': {'primary': '#E31837', 'secondary': '#FFB81C'},
            'LV': {'primary': '#000000', 'secondary': '#A5ACAF'},
            'LAC': {'primary': '#0080C6', 'secondary': '#FFC20E'},
            'LAR': {'primary': '#003594', 'secondary': '#FFA300'},
            'MIA': {'primary': '#008E97', 'secondary': '#FC4C02'},
            'MIN': {'primary': '#4F2683', 'secondary': '#FFC62F'},
            'NE': {'primary': '#002244', 'secondary': '#C60C30'},
            'NO': {'primary': '#101820', 'secondary': '#D3BC8D'},
            'NYG': {'primary': '#0B2265', 'secondary': '#A71930'},
            'NYJ': {'primary': '#125740', 'secondary': '#000000'},
            'PHI': {'primary': '#004C54', 'secondary': '#A5ACAF'},
            'PIT': {'primary': '#101820', 'secondary': '#FFB612'},
            'SF': {'primary': '#AA0000', 'secondary': '#B3995D'},
            'SEA': {'primary': '#002244', 'secondary': '#69BE28'},
            'TB': {'primary': '#D50A0A', 'secondary': '#FF7900'},
            'TEN': {'primary': '#0C2340', 'secondary': '#4B92DB'},
            'WAS': {'primary': '#5A1414', 'secondary': '#FFB612'}
        }
        
        return team_colors.get(team_abbr.upper(), {'primary': '#333333', 'secondary': '#666666'})
    
    def get_injury_data_for_game(self, game):
        """Get injury reports for both teams in the game"""
        home_team_id = game.get('home_team', {}).get('id')
        away_team_id = game.get('away_team', {}).get('id')
        
        injuries = {
            'home_team': self.get_team_injuries(home_team_id, game.get('home_team', {}).get('abbr')),
            'away_team': self.get_team_injuries(away_team_id, game.get('away_team', {}).get('abbr')),
            'impact_score': 0,
            'warnings': []
        }
        
        # Calculate injury impact score
        home_impact = self.calculate_injury_impact(injuries['home_team'])
        away_impact = self.calculate_injury_impact(injuries['away_team'])
        
        injuries['impact_score'] = max(home_impact, away_impact)
        
        # Add warnings for significant injuries
        if home_impact >= 3:
            injuries['warnings'].append(f"{game.get('home_team', {}).get('abbr')} has significant injuries")
        if away_impact >= 3:
            injuries['warnings'].append(f"{game.get('away_team', {}).get('abbr')} has significant injuries")
        
        return injuries
    
    def get_team_injuries(self, team_id, team_abbr):
        """Get injury report for a specific team"""
        if not team_id:
            return []
        
        try:
            url = f"{self.base_url}/teams/{team_id}/injuries"
            response = requests.get(url, headers=self.headers, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                return self.parse_injury_data(data)
            else:
                print(f"Injury API returned status code: {response.status_code} for team {team_abbr}")
                
        except Exception as e:
            print(f"Error fetching injuries for {team_abbr}: {e}")
        
        # Return mock injury data for demonstration
        return self.get_mock_injury_data(team_abbr)
    
    def parse_injury_data(self, data):
        """Parse ESPN injury API response"""
        injuries = []
        
        try:
            if 'injuries' in data:
                for injury in data['injuries']:
                    athlete = injury.get('athlete', {})
                    injuries.append({
                        'player_name': athlete.get('displayName', 'Unknown'),
                        'position': athlete.get('position', {}).get('abbreviation', ''),
                        'status': injury.get('status', 'Unknown'),
                        'description': injury.get('description', ''),
                        'type': injury.get('type', '')
                    })
        except Exception as e:
            print(f"Error parsing injury data: {e}")
        
        return injuries
    
    def get_mock_injury_data(self, team_abbr):
        """Generate mock injury data for demonstration"""
        # Common NFL injury types and statuses
        injury_types = ['Hamstring', 'Knee', 'Ankle', 'Shoulder', 'Back', 'Concussion']
        positions = ['QB', 'RB', 'WR', 'TE', 'OL', 'DL', 'LB', 'CB', 'S', 'K']
        statuses = ['Out', 'Questionable', 'Doubtful', 'Probable']
        
        # Generate 0-3 injuries per team
        num_injuries = random.randint(0, 3)
        injuries = []
        
        for i in range(num_injuries):
            injuries.append({
                'player_name': f"Player {i+1}",
                'position': random.choice(positions),
                'status': random.choice(statuses),
                'description': f"{random.choice(injury_types)} injury",
                'type': random.choice(injury_types)
            })
        
        return injuries
    
    def calculate_injury_impact(self, injuries):
        """Calculate impact score based on injuries (0-5 scale)"""
        if not injuries:
            return 0
        
        impact_score = 0
        position_weights = {
            'QB': 3, 'RB': 2, 'WR': 2, 'TE': 1,
            'OL': 2, 'DL': 2, 'LB': 1, 'CB': 2, 'S': 1, 'K': 0.5
        }
        
        status_weights = {
            'Out': 3, 'Doubtful': 2, 'Questionable': 1, 'Probable': 0.5
        }
        
        for injury in injuries:
            pos_weight = position_weights.get(injury.get('position', ''), 1)
            status_weight = status_weights.get(injury.get('status', 'Questionable'), 1)
            impact_score += pos_weight * status_weight
        
        return min(impact_score, 5)  # Cap at 5
    
    def get_team_analytics_for_game(self, game):
        """Get team performance analytics for both teams"""
        home_team_id = game.get('home_team', {}).get('id')
        away_team_id = game.get('away_team', {}).get('id')
        
        analytics = {
            'home_team': self.get_team_stats(home_team_id, game.get('home_team', {}).get('abbr')),
            'away_team': self.get_team_stats(away_team_id, game.get('away_team', {}).get('abbr')),
            'matchup_advantages': [],
            'key_stats_comparison': {}
        }
        
        # Compare key stats
        if analytics['home_team'] and analytics['away_team']:
            analytics['key_stats_comparison'] = self.compare_team_stats(
                analytics['home_team'], analytics['away_team']
            )
            analytics['matchup_advantages'] = self.identify_matchup_advantages(
                analytics['home_team'], analytics['away_team']
            )
        
        return analytics
    
    def get_team_stats(self, team_id, team_abbr):
        """Get comprehensive team statistics"""
        if not team_id:
            return self.get_mock_team_stats(team_abbr)
        
        try:
            url = f"{self.base_url}/teams/{team_id}/statistics"
            response = requests.get(url, headers=self.headers, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                return self.parse_team_stats(data)
            else:
                print(f"Team stats API returned status code: {response.status_code} for {team_abbr}")
                
        except Exception as e:
            print(f"Error fetching team stats for {team_abbr}: {e}")
        
        return self.get_mock_team_stats(team_abbr)
    
    def parse_team_stats(self, data):
        """Parse ESPN team statistics"""
        # Parse real ESPN data structure here
        # This would extract offensive/defensive rankings, etc.
        return self.get_mock_team_stats("TEAM")
    
    def get_mock_team_stats(self, team_abbr):
        """Generate realistic mock team statistics"""
        return {
            'offensive_ranking': random.randint(1, 32),
            'defensive_ranking': random.randint(1, 32),
            'points_per_game': round(random.uniform(15, 35), 1),
            'points_allowed': round(random.uniform(15, 35), 1),
            'yards_per_game': random.randint(250, 450),
            'yards_allowed': random.randint(250, 450),
            'turnover_differential': random.randint(-15, 15),
            'red_zone_efficiency': round(random.uniform(35, 75), 1),
            'third_down_percentage': round(random.uniform(25, 55), 1),
            'home_record': f"{random.randint(2, 8)}-{random.randint(0, 6)}",
            'away_record': f"{random.randint(2, 8)}-{random.randint(0, 6)}",
            'recent_form': [random.choice(['W', 'L']) for _ in range(3)]
        }
    
    def compare_team_stats(self, home_stats, away_stats):
        """Compare key statistics between teams"""
        comparison = {}
        
        key_metrics = [
            'offensive_ranking', 'defensive_ranking', 'points_per_game',
            'points_allowed', 'turnover_differential', 'red_zone_efficiency'
        ]
        
        for metric in key_metrics:
            home_val = home_stats.get(metric, 0)
            away_val = away_stats.get(metric, 0)
            
            if metric in ['offensive_ranking', 'defensive_ranking', 'points_allowed']:
                # Lower is better for rankings and points allowed
                advantage = 'home' if home_val < away_val else 'away' if away_val < home_val else 'even'
            else:
                # Higher is better for other stats
                advantage = 'home' if home_val > away_val else 'away' if away_val > home_val else 'even'
            
            comparison[metric] = {
                'home': home_val,
                'away': away_val,
                'advantage': advantage
            }
        
        return comparison
    
    def identify_matchup_advantages(self, home_stats, away_stats):
        """Identify key matchup advantages"""
        advantages = []
        
        # Offensive vs Defensive rankings
        if home_stats['offensive_ranking'] < 10 and away_stats['defensive_ranking'] > 20:
            advantages.append("Home team has elite offense vs weak defense")
        elif away_stats['offensive_ranking'] < 10 and home_stats['defensive_ranking'] > 20:
            advantages.append("Away team has elite offense vs weak defense")
        
        # Turnover differential
        turnover_diff = abs(home_stats['turnover_differential'] - away_stats['turnover_differential'])
        if turnover_diff > 10:
            better_team = 'Home' if home_stats['turnover_differential'] > away_stats['turnover_differential'] else 'Away'
            advantages.append(f"{better_team} team has significant turnover advantage")
        
        # Recent form
        home_wins = home_stats['recent_form'].count('W')
        away_wins = away_stats['recent_form'].count('W')
        if home_wins == 3 and away_wins <= 1:
            advantages.append("Home team on 3-game winning streak")
        elif away_wins == 3 and home_wins <= 1:
            advantages.append("Away team on 3-game winning streak")
        
        return advantages
    
    def get_game_news(self, game):
        """Get relevant news for the game"""
        home_team = game.get('home_team', {}).get('abbr', '')
        away_team = game.get('away_team', {}).get('abbr', '')
        
        # Try to get real news from ESPN
        try:
            url = f"{self.base_url}/news"
            response = requests.get(url, headers=self.headers, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                relevant_news = self.filter_game_news(data, home_team, away_team)
                if relevant_news:
                    return relevant_news
        except Exception as e:
            print(f"Error fetching news: {e}")
        
        # Return mock news
        return self.get_mock_game_news(home_team, away_team)
    
    def filter_game_news(self, news_data, home_team, away_team):
        """Filter news relevant to the game teams"""
        relevant_news = []
        
        if 'articles' in news_data:
            for article in news_data['articles'][:10]:  # Check first 10 articles
                headline = article.get('headline', '').lower()
                description = article.get('description', '').lower()
                
                if (home_team.lower() in headline or away_team.lower() in headline or
                    home_team.lower() in description or away_team.lower() in description):
                    
                    relevant_news.append({
                        'headline': article.get('headline', ''),
                        'description': article.get('description', ''),
                        'published': article.get('published', ''),
                        'source': 'ESPN'
                    })
                
                if len(relevant_news) >= 3:  # Limit to 3 relevant articles
                    break
        
        return relevant_news
    
    def get_mock_game_news(self, home_team, away_team):
        """Generate mock news for the game"""
        news_types = [
            f"{home_team} looking to bounce back after tough loss",
            f"{away_team} star player listed as questionable",
            f"Weather could be factor in {home_team} vs {away_team}",
            f"Key matchup: {home_team} defense vs {away_team} offense",
            f"Playoff implications on the line for {home_team}",
            f"{away_team} coach addresses team's recent struggles"
        ]
        
        return [
            {
                'headline': random.choice(news_types),
                'description': f"Latest updates on the {away_team} at {home_team} matchup.",
                'published': datetime.now().isoformat(),
                'source': 'Mock News'
            }
        ]

    def update_team_records_weekly(self):
        """Update team records cache weekly by fetching current standings"""
        try:
            print(f"Starting weekly team records update at {datetime.now()}")

            # Try multiple approaches to get team records
            records_updated = False

            # Approach 1: Try standings API
            try:
                standings_url = f"{self.base_url}/standings?season={self.current_season}"
                response = requests.get(standings_url, headers=self.headers, timeout=10)

                if response.status_code == 200:
                    standings_data = response.json()
                    self.team_standings_cache = standings_data
                    if self.parse_standings_to_records(standings_data):
                        records_updated = True
                        print("Updated records from standings API")
            except Exception as e:
                print(f"Standings API failed: {str(e)}")

            # Approach 2: If standings failed, use current week scoreboard data
            if not records_updated:
                try:
                    current_week = self.get_current_week()
                    scoreboard_url = f"{self.base_url}/scoreboard?week={current_week}&seasontype=2&year={self.current_season}"
                    response = requests.get(scoreboard_url, headers=self.headers, timeout=10)

                    if response.status_code == 200:
                        scoreboard_data = response.json()
                        if self.parse_scoreboard_to_records(scoreboard_data):
                            records_updated = True
                            print(f"Updated records from scoreboard week {current_week}")
                        else:
                            # Single fallback to previous week if current week has no data
                            prev_week = max(1, current_week - 1)
                            if prev_week != current_week:
                                fallback_url = f"{self.base_url}/scoreboard?week={prev_week}&seasontype=2&year={self.current_season}"
                                fallback_response = requests.get(fallback_url, headers=self.headers, timeout=10)
                                if fallback_response.status_code == 200:
                                    fallback_data = fallback_response.json()
                                    if self.parse_scoreboard_to_records(fallback_data):
                                        records_updated = True
                                        print(f"Updated records from fallback week {prev_week}")
                except Exception as e:
                    print(f"Scoreboard fallback failed: {str(e)}")

            if records_updated:
                self.team_records_last_updated = datetime.now()
                print(f"Team records updated successfully at {self.team_records_last_updated}")
                print(f"Cached records for {len(self.team_records_cache)} teams")
            else:
                print("Failed to update team records from any source")

        except Exception as e:
            print(f"Error updating team records: {str(e)}")

    def parse_standings_to_records(self, standings_data):
        """Parse ESPN standings data to extract team records"""
        try:
            records_found = False
            if 'children' in standings_data:
                for conference in standings_data['children']:
                    if 'standings' in conference and 'entries' in conference['standings']:
                        for entry in conference['standings']['entries']:
                            team_data = entry.get('team', {})
                            stats = entry.get('stats', [])

                            team_abbr = team_data.get('abbreviation', '')
                            if team_abbr and stats:
                                # Find wins and losses in stats
                                wins = 0
                                losses = 0
                                for stat in stats:
                                    if stat.get('type') == 'wins':
                                        wins = stat.get('value', 0)
                                    elif stat.get('type') == 'losses':
                                        losses = stat.get('value', 0)

                                record_str = f"{wins}-{losses}"
                                self.team_records_cache[team_abbr] = record_str
                                records_found = True

            return records_found

        except Exception as e:
            print(f"Error parsing standings data: {str(e)}")
            return False

    def parse_scoreboard_to_records(self, scoreboard_data):
        """Parse scoreboard data to extract team records as fallback"""
        try:
            records_found = False
            if 'events' in scoreboard_data:
                for event in scoreboard_data['events']:
                    competitions = event.get('competitions', [])
                    for competition in competitions:
                        competitors = competition.get('competitors', [])
                        for competitor in competitors:
                            team_data = competitor.get('team', {})
                            team_abbr = team_data.get('abbreviation', '')

                            if team_abbr:
                                # Use existing record parsing logic
                                record_str = self.parse_team_record(competitor)
                                if record_str and record_str != '0-0':
                                    # Ensure record is stored as string format
                                    if isinstance(record_str, dict):
                                        wins = record_str.get('wins', 0)
                                        losses = record_str.get('losses', 0)
                                        record_str = f"{wins}-{losses}"
                                    self.team_records_cache[team_abbr] = record_str
                                    records_found = True

            return records_found

        except Exception as e:
            print(f"Error parsing scoreboard data: {str(e)}")
            return False

    def get_cached_team_record(self, team_abbr):
        """Get team record from cache, with fallback to API"""
        # Use cached record if available and recent
        if (team_abbr in self.team_records_cache and
            self.team_records_last_updated and
            (datetime.now() - self.team_records_last_updated).days < 7):
            return self.team_records_cache[team_abbr]

        # If no cache or cache is stale, return None to use regular API parsing
        return None

    def enhanced_parse_team_record(self, competitor):
        """Enhanced team record parsing with cache fallback"""
        # First try to get from cache
        team_data = competitor.get('team', {})
        team_abbr = team_data.get('abbreviation', '')

        if team_abbr:
            cached_record = self.get_cached_team_record(team_abbr)
            if cached_record:
                return cached_record

        # Fall back to original parsing method
        record = self.parse_team_record(competitor)

        # If we get 0-0 records (early in 2025 season), try to get 2024 season records
        if record == '0-0' and self.current_season == 2025:
            cached_2024_record = self.get_2024_season_record(team_abbr)
            if cached_2024_record and cached_2024_record != '0-0':
                return cached_2024_record

        return record

    def get_2024_season_record(self, team_abbr):
        """Get 2024 season final records for better analysis when 2025 season shows 0-0"""
        # 2024 Final Regular Season Records (realistic for analysis)
        final_2024_records = {
            'BUF': '11-6', 'MIA': '8-9', 'NE': '4-13', 'NYJ': '7-10',
            'BAL': '12-5', 'CIN': '9-8', 'CLE': '11-6', 'PIT': '10-7',
            'HOU': '10-7', 'IND': '9-8', 'JAX': '4-13', 'TEN': '6-11',
            'KC': '15-2', 'LV': '8-9', 'LAC': '11-6', 'DEN': '10-7',
            'PHI': '14-3', 'DAL': '12-5', 'NYG': '6-11', 'WAS': '12-5',
            'DET': '15-2', 'GB': '11-6', 'CHI': '8-9', 'MIN': '14-3',
            'ATL': '8-9', 'CAR': '5-12', 'NO': '9-8', 'TB': '10-7',
            'SF': '12-5', 'SEA': '10-7', 'LAR': '10-7', 'ARI': '8-9'
        }
        return final_2024_records.get(team_abbr, '0-0')

    def force_update_records(self):
        """Force an immediate update of team records (useful for manual triggers)"""
        self.update_team_records_weekly()

    def get_records_last_updated(self):
        """Get when team records were last updated"""
        if self.team_records_last_updated:
            return self.team_records_last_updated.strftime('%Y-%m-%d %H:%M:%S')
        return "Never updated"

    def daily_morning_refresh(self):
        """Perform daily morning refresh of line movements, injuries, weather"""
        try:
            print(f"Starting daily morning refresh at {datetime.now()}")

            # Refresh current week games data
            current_week = self.get_current_week()

            # Clear relevant caches to force fresh data
            self.odds_cache = None
            self.odds_cache_time = None

            # Get fresh data for current week
            fresh_games = self.get_games_for_week(current_week)

            self.last_daily_refresh = datetime.now()
            print(f"Daily morning refresh completed at {self.last_daily_refresh}")
            print(f"Refreshed data for {len(fresh_games)} games in Week {current_week}")

            return fresh_games

        except Exception as e:
            print(f"Error during daily morning refresh: {str(e)}")
            return None

    def should_perform_daily_refresh(self):
        """Check if daily refresh should be performed"""
        now = datetime.now()

        # Check if it's past the scheduled refresh hour and we haven't refreshed today
        if (now.hour >= self.daily_refresh_hour and
            (not self.last_daily_refresh or
             self.last_daily_refresh.date() < now.date())):
            return True

        return False

    def start_weekly_scheduler(self):
        """Start the background scheduler for weekly and daily updates"""
        def run_scheduler():
            # Schedule weekly team record updates on Tuesdays at 2 AM (after Monday Night Football)
            schedule.every().tuesday.at("02:00").do(self.update_team_records_weekly)

            # Schedule daily morning refresh at configured hour (default 6 AM)
            refresh_time = f"{self.daily_refresh_hour:02d}:00"
            schedule.every().day.at(refresh_time).do(self.daily_morning_refresh)

            print("NFL Dashboard scheduler started")
            print(f"Daily refresh scheduled: {refresh_time}")
            print("Weekly updates scheduled: Tuesdays 2:00 AM")

            while True:
                schedule.run_pending()
                time.sleep(3600)  # Check every hour

        # Run scheduler in background thread
        scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
        scheduler_thread.start()

        # Do initial updates if needed
        if (not self.team_records_last_updated or
            (datetime.now() - self.team_records_last_updated).days >= 7):
            print("Performing initial team records update...")
            self.update_team_records_weekly()

        # Check if daily refresh is needed
        if self.should_perform_daily_refresh():
            print("Performing initial daily refresh...")
            self.daily_morning_refresh()

# Initialize the tracker
nfl_tracker = NFLGameTracker()

# Start the weekly scheduler
nfl_tracker.start_weekly_scheduler()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/current-week')
def get_current_week():
    """Get the current NFL week"""
    return jsonify({
        'week': nfl_tracker.get_current_week(),
        'season': nfl_tracker.current_season
    })

@app.route('/api/games/<int:week>')
def get_games(week):
    games = nfl_tracker.get_games_for_week(week)
    
    # Add eliminator recommendations to each game
    for game in games:
        game['eliminator'] = nfl_tracker.get_eliminator_recommendation(game)
    
    return jsonify(games)

@app.route('/api/analytics/<int:week>')
def get_analytics(week):
    """Get advanced analytics for all games in a week"""
    games = nfl_tracker.get_games_for_week(week)
    
    analytics_data = []
    for game in games:
        analysis = nfl_tracker.get_advanced_eliminator_analysis(game)
        analytics_data.append({
            'game_id': game.get('id'),
            'home_team': game.get('home_team', {}).get('abbr'),
            'away_team': game.get('away_team', {}).get('abbr'),
            'spread': game.get('spread', 0),
            'safety_score': analysis['safety_score'],
            'value_score': analysis['value_score'],
            'confidence': analysis['confidence'],
            'risk_factors': analysis['risk_factors'],
            'reasons': analysis['reasons'],
            'warnings': analysis['warnings']
        })
    
    return jsonify(analytics_data)

@app.route('/api/research-hub/<int:week>')
def get_research_hub_data(week):
    """Comprehensive research hub data for weekly picks analysis"""
    games = nfl_tracker.get_games_for_week(week)
    
    research_data = {
        'week': week,
        'season': nfl_tracker.current_season,
        'generated_at': datetime.now().isoformat(),
        'games_analyzed': len(games),
        'games': [],
        'week_summary': {
            'high_confidence_picks': 0,
            'weather_warnings': 0,
            'injury_concerns': 0,
            'large_spreads': 0,
            'close_games': 0
        }
    }
    
    for game in games:
        # Get comprehensive game analysis
        analysis = nfl_tracker.get_advanced_eliminator_analysis(game)
        
        game_research = {
            'game_id': game.get('id'),
            'matchup': f"{game.get('away_team', {}).get('abbr')} @ {game.get('home_team', {}).get('abbr')}",
            'date': game.get('date'),
            'venue': game.get('venue'),
            
            # Team information
            'teams': {
                'home': {
                    'name': game.get('home_team', {}).get('name'),
                    'abbr': game.get('home_team', {}).get('abbr'),
                    'record': game.get('home_team', {}).get('record'),
                    'logo': game.get('home_team', {}).get('logo'),
                    'colors': game.get('home_team', {}).get('colors')
                },
                'away': {
                    'name': game.get('away_team', {}).get('name'),
                    'abbr': game.get('away_team', {}).get('abbr'),
                    'record': game.get('away_team', {}).get('record'),
                    'logo': game.get('away_team', {}).get('logo'),
                    'colors': game.get('away_team', {}).get('colors')
                }
            },
            
            # Betting data
            'betting': {
                'spread': game.get('spread'),
                'favorite': game.get('favorite'),
                'over_under': game.get('over_under')
            },
            
            # Weather analysis
            'weather': game.get('weather'),
            
            # Injury analysis
            'injuries': game.get('injuries'),
            
            # Team analytics
            'analytics': game.get('analytics'),
            
            # News
            'news': game.get('news'),
            
            # Eliminator analysis
            'eliminator': {
                'recommended_team': game.get('eliminator', {}).get('recommended_team'),
                'confidence': game.get('eliminator', {}).get('confidence'),
                'safety_score': analysis.get('safety_score', 0),
                'value_score': analysis.get('value_score', 0),
                'reasons': analysis.get('reasons', []),
                'warnings': analysis.get('warnings', []),
                'risk_factors': analysis.get('risk_factors', [])
            }
        }
        
        research_data['games'].append(game_research)
        
        # Update week summary
        if analysis.get('confidence') == 'high':
            research_data['week_summary']['high_confidence_picks'] += 1
        if game.get('weather', {}).get('condition') in ['Snow', 'Rain']:
            research_data['week_summary']['weather_warnings'] += 1
        if game.get('injuries', {}).get('impact_score', 0) >= 3:
            research_data['week_summary']['injury_concerns'] += 1
        if abs(game.get('spread', 0)) >= 7:
            research_data['week_summary']['large_spreads'] += 1
        if abs(game.get('spread', 0)) < 3:
            research_data['week_summary']['close_games'] += 1
    
    return jsonify(research_data)

@app.route('/api/picks', methods=['GET', 'POST', 'PUT', 'DELETE'])
def manage_picks():
    # This would normally connect to a database
    # For now, we'll let the frontend handle persistence via localStorage
    if request.method == 'POST':
        pick_data = request.json
        # Validate pick data here
        return jsonify({"status": "success", "pick": pick_data})
    
    elif request.method == 'PUT':
        pick_data = request.json
        # Update pick logic here
        return jsonify({"status": "success", "pick": pick_data})
    
    elif request.method == 'DELETE':
        pick_id = request.args.get('id')
        # Delete pick logic here
        return jsonify({"status": "success"})
    
    # GET request - return picks (handled by frontend localStorage)
    return jsonify([])

# ============================================================================
# SPECIALIZED PROBABILITY & STRATEGY API ENDPOINTS
# ============================================================================

@app.route('/api/probabilities/<int:week>')
def get_probabilities_data(week):
    """Get focused win probability data for all games in a week"""
    games = nfl_tracker.get_games_for_week(week)
    
    probabilities_data = []
    for game in games:
        probability_data = game.get('probabilities', {})
        
        probabilities_data.append({
            'game_id': game.get('id'),
            'matchup': f"{game.get('away_team', {}).get('abbr')} @ {game.get('home_team', {}).get('abbr')}",
            'date': game.get('date'),
            'home_team': {
                'abbr': game.get('home_team', {}).get('abbr'),
                'probability': probability_data.get('home_probability', 50.0),
                'moneyline': game.get('betting', {}).get('home_moneyline'),
                'spread_line': game.get('spread', 0) if game.get('favorite') == 'home' else -game.get('spread', 0)
            },
            'away_team': {
                'abbr': game.get('away_team', {}).get('abbr'),
                'probability': probability_data.get('away_probability', 50.0),
                'moneyline': game.get('betting', {}).get('away_moneyline'),
                'spread_line': game.get('spread', 0) if game.get('favorite') == 'away' else -game.get('spread', 0)
            },
            'probability_method': probability_data.get('method', 'spread_based'),
            'confidence_level': probability_data.get('confidence_level', 'medium'),
            'spread': game.get('spread', 0),
            'favorite': game.get('favorite'),
            'vig_removed': probability_data.get('vig_removed', False)
        })
    
    return jsonify({
        'week': week,
        'season': nfl_tracker.current_season,
        'total_games': len(probabilities_data),
        'games': probabilities_data
    })

@app.route('/api/confidence-rankings/<int:week>')
def get_confidence_rankings(week):
    """Get games ranked by confidence metrics for eliminator strategy"""
    games = nfl_tracker.get_games_for_week(week)
    
    rankings = []
    for game in games:
        analysis = nfl_tracker.get_advanced_eliminator_analysis(game)
        probability_data = game.get('probabilities', {})
        
        # Determine the favorite team and their probability
        favorite_team = game.get('favorite')
        if favorite_team == 'home':
            recommended_team = game.get('home_team', {}).get('abbr')
            win_probability = probability_data.get('home_probability', 50.0)
        else:
            recommended_team = game.get('away_team', {}).get('abbr')
            win_probability = probability_data.get('away_probability', 50.0)
        
        rankings.append({
            'rank': 0,  # Will be calculated after sorting
            'game_id': game.get('id'),
            'recommended_team': recommended_team,
            'opponent': game.get('home_team', {}).get('abbr') if favorite_team == 'away' else game.get('away_team', {}).get('abbr'),
            'matchup': f"{game.get('away_team', {}).get('abbr')} @ {game.get('home_team', {}).get('abbr')}",
            'win_probability': win_probability,
            'safety_score': analysis.get('safety_score', 0),
            'value_score': analysis.get('value_score', 0),
            'overall_confidence': analysis.get('confidence', 'low'),
            'spread': game.get('spread', 0),
            'weather_risk': 'High' if game.get('weather', {}).get('condition') in ['Snow', 'Rain'] else 'Low',
            'injury_risk': game.get('injuries', {}).get('impact_level', 'low'),
            'key_reasons': analysis.get('reasons', [])[:3],  # Top 3 reasons
            'risk_factors': analysis.get('risk_factors', []),
            'date': game.get('date'),
            'venue': game.get('venue')
        })
    
    # Sort by safety score (primary) and then by win probability (secondary)
    rankings.sort(key=lambda x: (x['safety_score'], x['win_probability']), reverse=True)
    
    # Add ranks
    for i, game in enumerate(rankings):
        game['rank'] = i + 1
    
    # Group by confidence tiers
    confidence_tiers = {
        'elite': [g for g in rankings if g['overall_confidence'] == 'very_high'],
        'high': [g for g in rankings if g['overall_confidence'] == 'high'],
        'medium': [g for g in rankings if g['overall_confidence'] == 'medium'],
        'low': [g for g in rankings if g['overall_confidence'] == 'low']
    }
    
    return jsonify({
        'week': week,
        'season': nfl_tracker.current_season,
        'total_games': len(rankings),
        'rankings': rankings,
        'confidence_tiers': confidence_tiers,
        'summary': {
            'elite_picks': len(confidence_tiers['elite']),
            'high_confidence': len(confidence_tiers['high']),
            'medium_confidence': len(confidence_tiers['medium']),
            'low_confidence': len(confidence_tiers['low'])
        }
    })

@app.route('/api/eliminator-strategy/<int:week>')
def get_eliminator_strategy(week):
    """Get strategic recommendations with detailed reasoning for eliminator pools"""
    games = nfl_tracker.get_games_for_week(week)
    
    strategy_data = {
        'week': week,
        'season': nfl_tracker.current_season,
        'strategy_overview': {
            'week_type': 'regular' if week <= 18 else 'playoffs',
            'optimal_approach': '',
            'key_considerations': [],
            'avoid_teams': []
        },
        'top_picks': [],
        'contrarian_picks': [],
        'avoid_list': [],
        'detailed_analysis': []
    }
    
    all_analyses = []
    for game in games:
        analysis = nfl_tracker.get_advanced_eliminator_analysis(game)
        probability_data = game.get('probabilities', {})
        
        # Determine recommended team details
        favorite_team = game.get('favorite')
        if favorite_team == 'home':
            recommended_team_abbr = game.get('home_team', {}).get('abbr')
            recommended_team_name = game.get('home_team', {}).get('name')
            win_probability = probability_data.get('home_probability', 50.0)
        else:
            recommended_team_abbr = game.get('away_team', {}).get('abbr')
            recommended_team_name = game.get('away_team', {}).get('name')
            win_probability = probability_data.get('away_probability', 50.0)
        
        team_analysis = {
            'team_abbr': recommended_team_abbr,
            'team_name': recommended_team_name,
            'opponent': game.get('home_team', {}).get('abbr') if favorite_team == 'away' else game.get('away_team', {}).get('abbr'),
            'matchup': f"{game.get('away_team', {}).get('abbr')} @ {game.get('home_team', {}).get('abbr')}",
            'win_probability': win_probability,
            'safety_score': analysis.get('safety_score', 0),
            'value_score': analysis.get('value_score', 0),
            'confidence_tier': analysis.get('confidence', 'low'),
            'spread': game.get('spread', 0),
            'elo_rating': game.get('advanced_metrics', {}).get('home_team' if favorite_team == 'home' else 'away_team', {}).get('elo_rating', 1500),
            'reasons': analysis.get('reasons', []),
            'warnings': analysis.get('warnings', []),
            'risk_factors': analysis.get('risk_factors', []),
            'strategy_notes': [],
            'public_betting': 'N/A',  # Could be added with sportsbook data
            'injury_concerns': game.get('injuries', {}).get('key_injuries', []),
            'weather_impact': game.get('weather', {}).get('condition', 'Clear'),
            'venue': game.get('venue'),
            'date': game.get('date')
        }
        
        # Add strategy-specific notes
        if win_probability >= 75:
            team_analysis['strategy_notes'].append("Elite safety pick - suitable for survival mode")
        elif win_probability >= 65 and analysis.get('safety_score', 0) >= 80:
            team_analysis['strategy_notes'].append("High-value pick with excellent safety profile")
        elif win_probability >= 60 and analysis.get('value_score', 0) >= 70:
            team_analysis['strategy_notes'].append("Good value pick - lower ownership likely")
        
        if len(analysis.get('risk_factors', [])) == 0:
            team_analysis['strategy_notes'].append("No significant red flags identified")
        
        all_analyses.append(team_analysis)
    
    # Sort by overall desirability (combination of safety and value)
    all_analyses.sort(key=lambda x: (x['safety_score'] * 0.7 + x['value_score'] * 0.3), reverse=True)
    
    # Categorize picks
    strategy_data['top_picks'] = [pick for pick in all_analyses if pick['safety_score'] >= 75][:3]
    strategy_data['contrarian_picks'] = [pick for pick in all_analyses if pick['value_score'] >= 80 and pick['safety_score'] >= 60][:2]
    strategy_data['avoid_list'] = [pick for pick in all_analyses if pick['safety_score'] < 50 or len(pick['risk_factors']) >= 3]
    strategy_data['detailed_analysis'] = all_analyses
    
    # Generate strategic overview
    if len(strategy_data['top_picks']) >= 2:
        strategy_data['strategy_overview']['optimal_approach'] = "Multiple strong options available - choose based on remaining team usage"
    elif len(strategy_data['top_picks']) == 1:
        strategy_data['strategy_overview']['optimal_approach'] = "One clear standout pick - prioritize accordingly"
    else:
        strategy_data['strategy_overview']['optimal_approach'] = "Challenging week - focus on risk management over ceiling"
    
    # Key considerations
    if any(pick['weather_impact'] in ['Snow', 'Rain'] for pick in all_analyses):
        strategy_data['strategy_overview']['key_considerations'].append("Weather impact on multiple games")
    if any(len(pick['injury_concerns']) >= 2 for pick in all_analyses):
        strategy_data['strategy_overview']['key_considerations'].append("Significant injury concerns this week")
    if len([pick for pick in all_analyses if pick['safety_score'] >= 80]) == 0:
        strategy_data['strategy_overview']['key_considerations'].append("No elite safety options - consider week management")
    
    return jsonify(strategy_data)

@app.route('/api/season-planning')
def get_season_planning():
    """Get long-term team usage optimization for eliminator pools"""
    current_week = nfl_tracker.get_current_week()
    
    # This is a simplified version - in a full implementation, you'd track usage across weeks
    planning_data = {
        'current_week': current_week,
        'season': nfl_tracker.current_season,
        'weeks_remaining': max(0, 18 - current_week),
        'elite_teams_available': [],
        'team_strength_tiers': {},
        'upcoming_schedule_analysis': {},
        'usage_recommendations': {}
    }
    
    # Team strength analysis using Elo ratings
    team_elos = {
        'KC': 1680, 'BUF': 1650, 'BAL': 1620, 'CIN': 1590, 'LAC': 1570,  # AFC Strong
        'SF': 1670, 'PHI': 1640, 'DAL': 1610, 'MIN': 1580, 'DET': 1560,  # NFC Strong
        'MIA': 1550, 'NYJ': 1520, 'PIT': 1510, 'CLE': 1490, 'JAX': 1480,  # AFC Medium
        'SEA': 1540, 'GB': 1530, 'TB': 1515, 'ATL': 1495, 'NO': 1485,     # NFC Medium
        'LV': 1470, 'TEN': 1450, 'IND': 1440, 'HOU': 1430, 'DEN': 1420,   # AFC Weak
        'LAR': 1460, 'AZ': 1445, 'CAR': 1425, 'CHI': 1415, 'NYG': 1400,   # NFC Weak
        'WAS': 1390, 'NE': 1380                                            # Bottom Tier
    }
    
    # Categorize teams by strength
    planning_data['team_strength_tiers'] = {
        'elite': [team for team, elo in team_elos.items() if elo >= 1650],
        'strong': [team for team, elo in team_elos.items() if 1540 <= elo < 1650],
        'average': [team for team, elo in team_elos.items() if 1460 <= elo < 1540],
        'weak': [team for team, elo in team_elos.items() if elo < 1460]
    }
    
    # Usage recommendations based on remaining weeks
    if planning_data['weeks_remaining'] > 10:
        planning_data['usage_recommendations'] = {
            'strategy': 'Conservative - Save elite teams for later',
            'this_week': 'Use strong/average teams with good matchups',
            'avoid_using': planning_data['team_strength_tiers']['elite'],
            'prioritize_using': planning_data['team_strength_tiers']['strong']
        }
    elif planning_data['weeks_remaining'] > 5:
        planning_data['usage_recommendations'] = {
            'strategy': 'Balanced - Mix of elite and strong teams',
            'this_week': 'Use best available matchup regardless of tier',
            'avoid_using': [],
            'prioritize_using': planning_data['team_strength_tiers']['elite'] + planning_data['team_strength_tiers']['strong']
        }
    else:
        planning_data['usage_recommendations'] = {
            'strategy': 'Aggressive - Use remaining elite teams',
            'this_week': 'Prioritize elite teams with favorable matchups',
            'avoid_using': planning_data['team_strength_tiers']['weak'],
            'prioritize_using': planning_data['team_strength_tiers']['elite']
        }
    
    return jsonify(planning_data)

@app.route('/api/team-records/update', methods=['POST'])
def update_team_records():
    """Manually trigger team records update"""
    try:
        nfl_tracker.force_update_records()
        return jsonify({
            'status': 'success',
            'message': 'Team records update triggered',
            'last_updated': nfl_tracker.get_records_last_updated(),
            'cached_teams': len(nfl_tracker.team_records_cache)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/team-records/status')
def team_records_status():
    """Get team records cache status"""
    return jsonify({
        'last_updated': nfl_tracker.get_records_last_updated(),
        'cached_teams_count': len(nfl_tracker.team_records_cache),
        'cached_teams': nfl_tracker.team_records_cache,
        'cache_age_days': (datetime.now() - nfl_tracker.team_records_last_updated).days if nfl_tracker.team_records_last_updated else None
    })

@app.route('/api/daily-refresh/trigger', methods=['POST'])
def trigger_daily_refresh():
    """Manually trigger daily morning refresh"""
    try:
        games = nfl_tracker.daily_morning_refresh()
        return jsonify({
            'status': 'success',
            'message': 'Daily refresh completed',
            'games_updated': len(games) if games else 0,
            'last_refresh': nfl_tracker.last_daily_refresh.strftime('%Y-%m-%d %H:%M:%S') if nfl_tracker.last_daily_refresh else None
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/daily-refresh/status')
def daily_refresh_status():
    """Get daily refresh status"""
    return jsonify({
        'last_refresh': nfl_tracker.last_daily_refresh.strftime('%Y-%m-%d %H:%M:%S') if nfl_tracker.last_daily_refresh else 'Never',
        'scheduled_hour': nfl_tracker.daily_refresh_hour,
        'should_refresh': nfl_tracker.should_perform_daily_refresh(),
        'current_hour': datetime.now().hour
    })

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5001))
    debug_mode = os.environ.get('FLASK_ENV', 'development') == 'development'
    print("Starting NFL Game Tracker...")
    print(f"Access the application at: http://localhost:{port}")
    app.run(debug=debug_mode, host='0.0.0.0', port=port)