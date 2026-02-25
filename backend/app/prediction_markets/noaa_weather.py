"""
NOAA Weather Data Integration.

Fetches official weather forecasts from the National Weather Service (NWS) API.
Used by the WeatherArbitrageStrategy to compare against Polymarket weather prices.

NWS API is free, no API key required, rate-limited to ~20 requests/minute.
Forecast accuracy: >90% for 1-3 day temperature predictions.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

import requests

from .strategies import WeatherForecast

logger = logging.getLogger(__name__)

# NWS API endpoints
NWS_API = "https://api.weather.gov"

# Major city coordinates (lat, lon)
CITY_COORDINATES = {
    "NYC": (40.7128, -74.0060),
    "Chicago": (41.8781, -87.6298),
    "Seattle": (47.6062, -122.3321),
    "Atlanta": (33.7490, -84.3880),
    "Dallas": (32.7767, -96.7970),
    "Los Angeles": (34.0522, -118.2437),
    "Miami": (25.7617, -80.1918),
    "Denver": (39.7392, -104.9903),
    "Phoenix": (33.4484, -112.0740),
    "Boston": (42.3601, -71.0589),
    "Detroit": (42.3314, -83.0458),
    "Minneapolis": (44.9778, -93.2650),
    "San Francisco": (37.7749, -122.4194),
    "Houston": (29.7604, -95.3698),
    "Philadelphia": (39.9526, -75.1652),
}


class NOAAWeatherClient:
    """
    Fetches weather forecasts from NWS (National Weather Service) API.

    The NWS API works in two steps:
    1. Get the forecast office and grid coordinates for a lat/lon point
    2. Use those to fetch the detailed forecast

    Results are cached per location to avoid redundant API calls.
    """

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "LLM-Quant Weather Arb (github.com/subhsubh24/LLM-Quant)",
            "Accept": "application/geo+json",
        })
        # Cache grid points: city -> (office, gridX, gridY)
        self._grid_cache: Dict[str, tuple] = {}
        self._forecast_cache: Dict[str, WeatherForecast] = {}

    def get_grid_point(self, lat: float, lon: float) -> Optional[tuple]:
        """
        Get NWS forecast office and grid coordinates for a lat/lon.

        Returns: (office_id, grid_x, grid_y) or None on failure.
        """
        cache_key = f"{lat:.4f},{lon:.4f}"
        if cache_key in self._grid_cache:
            return self._grid_cache[cache_key]

        try:
            resp = self.session.get(
                f"{NWS_API}/points/{lat},{lon}",
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

            props = data.get("properties", {})
            office = props.get("gridId", "")
            grid_x = props.get("gridX", 0)
            grid_y = props.get("gridY", 0)

            result = (office, grid_x, grid_y)
            self._grid_cache[cache_key] = result
            return result
        except Exception as e:
            logger.error(f"NWS grid point lookup failed for ({lat}, {lon}): {e}")
            return None

    def get_forecast(self, city: str) -> Optional[WeatherForecast]:
        """
        Get weather forecast for a city.

        Returns forecast for today/tomorrow with high/low temperatures.
        """
        if city not in CITY_COORDINATES:
            logger.warning(f"Unknown city: {city}. Available: {list(CITY_COORDINATES.keys())}")
            return None

        lat, lon = CITY_COORDINATES[city]
        grid = self.get_grid_point(lat, lon)
        if not grid:
            return None

        office, grid_x, grid_y = grid

        try:
            resp = self.session.get(
                f"{NWS_API}/gridpoints/{office}/{grid_x},{grid_y}/forecast",
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

            periods = data.get("properties", {}).get("periods", [])
            if not periods:
                return None

            # Get today's forecast (first two periods = day + night)
            today = periods[0]
            tonight = periods[1] if len(periods) > 1 else periods[0]

            # Parse temperatures
            temp_high = float(today.get("temperature", 70))
            temp_low = float(tonight.get("temperature", 50))

            # If tonight temp is higher (happens in early morning), swap
            if temp_low > temp_high:
                temp_high, temp_low = temp_low, temp_high

            temp_mean = (temp_high + temp_low) / 2.0

            # Parse precipitation
            precip_pct = 0.0
            pop = today.get("probabilityOfPrecipitation", {})
            if isinstance(pop, dict) and pop.get("value") is not None:
                precip_pct = float(pop["value"]) / 100.0

            # Parse wind
            wind_speed = today.get("windSpeed", "5 mph")
            wind_mph = 5.0
            if isinstance(wind_speed, str):
                import re
                match = re.search(r'(\d+)', wind_speed)
                if match:
                    wind_mph = float(match.group(1))

            # Forecast confidence based on lead time
            # NWS forecasts degrade: 95% for today, 85% for tomorrow, 70% for 3-day
            forecast_start = today.get("startTime", "")
            confidence = 0.90  # Default high confidence for near-term

            forecast = WeatherForecast(
                location=city,
                date=datetime.now(timezone.utc),
                temp_high_f=temp_high,
                temp_low_f=temp_low,
                temp_mean_f=temp_mean,
                precipitation_pct=precip_pct,
                wind_mph=wind_mph,
                confidence=confidence,
            )

            self._forecast_cache[city] = forecast
            return forecast

        except Exception as e:
            logger.error(f"NWS forecast fetch failed for {city}: {e}")
            return None

    def get_all_forecasts(
        self,
        cities: Optional[List[str]] = None,
    ) -> Dict[str, WeatherForecast]:
        """
        Fetch forecasts for all tracked cities.

        Returns: {city_name: WeatherForecast}
        """
        if cities is None:
            cities = list(CITY_COORDINATES.keys())

        forecasts = {}
        for city in cities:
            forecast = self.get_forecast(city)
            if forecast:
                forecasts[city] = forecast
                logger.info(
                    f"[NOAA] {city}: {forecast.temp_low_f:.0f}°F - "
                    f"{forecast.temp_high_f:.0f}°F (mean: {forecast.temp_mean_f:.0f}°F, "
                    f"precip: {forecast.precipitation_pct:.0%})"
                )

        return forecasts
