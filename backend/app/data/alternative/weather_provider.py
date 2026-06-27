"""
Weather and climate data provider (NOAA).

You asked about weather specifically - here's why it actually matters
for markets, and it's NOT just agriculture:

DIRECT MARKET IMPACTS:

1. ENERGY SECTOR:
   - Cold winters = natural gas demand spike (UNG, energy stocks)
   - Hot summers = electricity demand spike (utilities)
   - Temperature deviations from normal predict energy commodity prices
   - Heating/Cooling Degree Days (HDD/CDD) are traded as derivatives

2. AGRICULTURE:
   - Drought = crop failure = grain price spikes (DBA)
   - Excess rain = planting delays = corn/soybean price impact
   - Temperature anomalies during growing season are critical

3. RETAIL:
   - Warm winters = lower heating costs, more discretionary spending
   - Severe weather = reduced foot traffic = lower retail sales
   - Hurricane season = insurance/reinsurance cost spikes

4. CONSTRUCTION/HOUSING:
   - Extreme cold = construction delays = housing start misses
   - Mild winters = accelerated building activity

5. BEHAVIORAL FINANCE:
   - "Sunshine effect" (Hirshleifer & Shumway, 2003):
     Stock returns are higher on sunny days at the exchange location
   - Seasonal Affective Disorder = lower risk appetite in winter
   - This is NOT a joke - it's been replicated across 26 countries

DATA SOURCE:
   NOAA Climate Data Online (CDO) - completely free
   Global Historical Climatology Network (GHCN) - daily data
   Heating/Cooling Degree Days from NOAA/weather.gov
"""

from datetime import date, timedelta
from typing import Optional, List
import pandas as pd
import numpy as np
import logging

from .base import AlternativeDataProvider, AltDataConfig

logger = logging.getLogger(__name__)


class WeatherProvider(AlternativeDataProvider):
    """
    Fetches weather data from NOAA and computes market-relevant features.

    Uses free NOAA Climate Data Online API or falls back to seasonal
    models based on historical climatology.

    Key locations: NYC (financial center), Houston (energy),
    Chicago (agriculture), National average
    """

    # NOAA CDO API (free, requires token from https://www.ncdc.noaa.gov/cdo-web/token)
    NOAA_BASE = "https://www.ncei.noaa.gov/cdo-web/api/v2"

    # Key weather stations (major financial/economic centers)
    STATIONS = {
        "nyc": "GHCND:USW00094728",      # Central Park, NYC
        "chicago": "GHCND:USW00094846",    # O'Hare, Chicago
        "houston": "GHCND:USW00012960",    # Houston Hobby
    }

    def __init__(self, config: Optional[AltDataConfig] = None):
        self.config = config or AltDataConfig()

    @property
    def name(self) -> str:
        return "weather"

    def get_feature_names(self) -> List[str]:
        return [
            # Temperature features
            "weather_temp_anomaly_nyc",
            "weather_temp_anomaly_national",
            "weather_hdd",  # Heating Degree Days
            "weather_cdd",  # Cooling Degree Days
            "weather_temp_vol",  # Temperature volatility
            # Seasonal/behavioral
            "weather_daylight_hours",
            "weather_daylight_change",
            "weather_sad_proxy",  # Seasonal Affective Disorder proxy
            # Extreme events
            "weather_extreme_cold",
            "weather_extreme_heat",
            # Energy impact
            "weather_energy_demand_proxy",
        ]

    def fetch(
        self,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """
        Fetch weather data and compute market-relevant features.

        Falls back to seasonal climatology model when API unavailable.
        """
        result = pd.DataFrame()

        # Try NOAA API first
        noaa_data = self._fetch_noaa(start_date, end_date)

        if noaa_data is not None and not noaa_data.empty:
            features = self._compute_features_from_data(noaa_data)
            if not features.empty:
                result = features
        else:
            # Fall back to seasonal climatology model
            logger.info("Weather: using seasonal climatology model")
            result = self._compute_seasonal_model(start_date, end_date)

        if not result.empty:
            result = self._resample_to_daily(result)

        logger.info(f"Weather: {len(result.columns)} features")
        return result

    def _fetch_noaa(
        self,
        start_date: date,
        end_date: date,
    ) -> Optional[pd.DataFrame]:
        """Fetch temperature data from NOAA CDO API."""
        # NOAA requires a free API token
        # For now, return None to use the seasonal model
        # In production, uncomment and set the token
        """
        import requests

        token = self.config.noaa_api_token  # Would need to add to config
        if not token:
            return None

        headers = {"token": token}
        params = {
            "datasetid": "GHCND",
            "stationid": self.STATIONS["nyc"],
            "datatypeid": "TAVG,TMAX,TMIN",
            "startdate": start_date.isoformat(),
            "enddate": end_date.isoformat(),
            "units": "standard",
            "limit": 1000,
        }

        response = requests.get(
            f"{self.NOAA_BASE}/data",
            headers=headers,
            params=params,
            timeout=30,
        )

        if response.status_code == 200:
            data = response.json()
            results = data.get("results", [])
            if results:
                df = pd.DataFrame(results)
                df["date"] = pd.to_datetime(df["date"])
                df = df.pivot(index="date", columns="datatype", values="value")
                return df

        return None
        """
        return None

    def _compute_features_from_data(
        self, data: pd.DataFrame
    ) -> pd.DataFrame:
        """Compute features from actual weather data."""
        result = pd.DataFrame(index=data.index)

        if "TAVG" in data.columns:
            # Temperature anomaly vs historical normal
            day_of_year = data.index.dayofyear
            normals = self._get_climatological_normals(day_of_year)
            result["weather_temp_anomaly_nyc"] = data["TAVG"] - normals
            result["weather_temp_anomaly_national"] = result["weather_temp_anomaly_nyc"]

            # HDD/CDD
            result["weather_hdd"] = np.maximum(65 - data["TAVG"], 0)
            result["weather_cdd"] = np.maximum(data["TAVG"] - 65, 0)

            # Temperature volatility
            result["weather_temp_vol"] = data["TAVG"].rolling(7).std()

        return result

    def _compute_seasonal_model(
        self,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """
        Seasonal climatology model based on date alone.

        Uses sinusoidal models of:
        - Temperature (annual cycle)
        - Daylight hours (latitude-dependent)
        - Historical temperature variance by month

        This is deterministic and reproducible - no randomness.
        """
        dates = pd.bdate_range(start=start_date, end=end_date)
        result = pd.DataFrame(index=dates)

        # Day of year (1-365)
        doy = dates.dayofyear.values.astype(float)

        # === Temperature model ===
        # NYC average temp follows a sinusoidal pattern
        # Average: ~55F, Amplitude: ~25F, Peak: ~July 20 (day 201)
        avg_temp_nyc = 55 + 25 * np.sin(2 * np.pi * (doy - 105) / 365)

        # Historical normals for temperature anomaly
        normals = self._get_climatological_normals(doy)

        # Temperature anomaly (0 by default in model, but varies with noise seed)
        # In the seasonal model, anomaly is 0 (we only know the expected pattern)
        result["weather_temp_anomaly_nyc"] = 0.0
        result["weather_temp_anomaly_national"] = 0.0

        # Heating Degree Days (base 65F): max(65 - temp, 0)
        result["weather_hdd"] = np.maximum(65 - avg_temp_nyc, 0)

        # Cooling Degree Days (base 65F): max(temp - 65, 0)
        result["weather_cdd"] = np.maximum(avg_temp_nyc - 65, 0)

        # Temperature volatility (higher in spring/fall = transition seasons)
        # Peaks around day 90 (spring) and 270 (fall)
        temp_vol = 3 + 2 * np.cos(4 * np.pi * doy / 365)
        result["weather_temp_vol"] = temp_vol

        # === Daylight features ===
        # NYC latitude ~40.7N
        lat_rad = np.radians(40.7)

        # Solar declination angle
        declination = 23.45 * np.sin(2 * np.pi * (doy - 81) / 365)
        decl_rad = np.radians(declination)

        # Hour angle at sunrise
        cos_hour = -np.tan(lat_rad) * np.tan(decl_rad)
        cos_hour = np.clip(cos_hour, -1, 1)
        hour_angle = np.degrees(np.arccos(cos_hour))

        # Daylight hours
        daylight = 2 * hour_angle / 15  # Convert degrees to hours
        result["weather_daylight_hours"] = daylight

        # Rate of change of daylight (most impactful for SAD)
        daylight_series = pd.Series(daylight, index=dates)
        result["weather_daylight_change"] = daylight_series.diff(5)

        # === Seasonal Affective Disorder proxy ===
        # Based on Kamstra, Kramer & Levi (2003) "Winter Blues"
        # SAD effect peaks around Dec 21 (shortest day) and troughs June 21
        # Modeled as negative deviation from average daylight
        avg_daylight = 12.0  # Average daylight at this latitude
        result["weather_sad_proxy"] = (avg_daylight - daylight) / avg_daylight

        # === Extreme weather indicators ===
        # Probability of extreme cold/heat by season
        # January peak cold probability, July peak heat probability
        result["weather_extreme_cold"] = np.maximum(
            0, np.cos(2 * np.pi * (doy - 15) / 365)  # Peaks mid-January
        ) * 0.3  # ~30% chance of extreme cold in peak winter

        result["weather_extreme_heat"] = np.maximum(
            0, np.cos(2 * np.pi * (doy - 200) / 365)  # Peaks mid-July
        ) * 0.2  # ~20% chance of extreme heat in peak summer

        # === Energy demand proxy ===
        # Combines HDD and CDD (U-shaped: high in winter AND summer)
        result["weather_energy_demand_proxy"] = (
            result["weather_hdd"] + result["weather_cdd"] * 1.5  # AC is expensive
        ) / 30  # Normalize

        return result

    def _get_climatological_normals(self, day_of_year) -> np.ndarray:
        """
        Return climatological normal temperatures by day of year.

        Based on 30-year normals for NYC Central Park.
        Uses sinusoidal approximation.
        """
        doy = np.asarray(day_of_year, dtype=float)
        # NYC: avg 55F, amplitude 25F, peak around day 201 (July 20)
        normals = 55 + 25 * np.sin(2 * np.pi * (doy - 105) / 365)
        return normals
