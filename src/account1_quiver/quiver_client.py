import logging
import time
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.shared.config import QUIVER_API_TOKEN, QUIVER_BASE_URL

logger = logging.getLogger(__name__)


class QuiverClient:
    """HTTP client for QuiverQuant API endpoints."""

    def __init__(self):
        self.base_url = QUIVER_BASE_URL
        self.headers = {
            "accept": "application/json",
            "Authorization": f"Token {QUIVER_API_TOKEN}",
        }
        self.request_delay = 1.0  # Rate limiting between requests
        self.timeout = 90  # Generous timeout for large endpoints
        self.max_retries = 3

        # Session with retry strategy for transient failures
        self.session = requests.Session()
        retry = Retry(
            total=self.max_retries,
            backoff_factor=2,  # 2s, 4s, 8s between retries
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def _get(self, endpoint: str, params: dict = None) -> Optional[list]:
        """Make a GET request to the QuiverQuant API with retries."""
        url = f"{self.base_url}{endpoint}"
        try:
            logger.info(f"Fetching {endpoint}...")
            resp = self.session.get(
                url, headers=self.headers, params=params, timeout=self.timeout
            )
            resp.raise_for_status()
            time.sleep(self.request_delay)
            data = resp.json()
            if isinstance(data, list):
                logger.info(f"{endpoint}: {len(data)} records")
                return data
            elif isinstance(data, dict) and "results" in data:
                logger.info(f"{endpoint}: {len(data['results'])} records")
                return data["results"]
            return data if isinstance(data, list) else [data]
        except requests.exceptions.HTTPError as e:
            logger.error(f"QuiverQuant API error for {endpoint}: {e}")
            return None
        except requests.exceptions.Timeout:
            logger.error(f"QuiverQuant timeout for {endpoint} after {self.timeout}s")
            return None
        except requests.exceptions.ConnectionError as e:
            logger.error(f"QuiverQuant connection error for {endpoint}: {e}")
            return None
        except Exception as e:
            logger.error(f"QuiverQuant request failed for {endpoint}: {e}")
            return None

    def get_congress_trades(self) -> Optional[list]:
        """Get recent congressional trades. Falls back to bulk endpoint."""
        data = self._get("/live/congresstrading")
        if data:
            return data
        # Fallback to bulk endpoint with recent page
        logger.info("Falling back to /bulk/congresstrading")
        return self._get("/bulk/congresstrading", params={"page_size": 500})

    def get_insider_trades(self) -> Optional[list]:
        """Get recent insider trades."""
        return self._get("/live/insiders")

    def get_gov_contracts(self) -> Optional[list]:
        """Get recent government contracts."""
        return self._get("/live/govcontracts")

    def get_lobbying(self) -> Optional[list]:
        """Get recent lobbying data."""
        return self._get("/live/lobbying")

    def get_wikipedia(self) -> Optional[list]:
        """Get Wikipedia traffic anomalies."""
        return self._get("/live/wikipedia")

    def get_wsb(self) -> Optional[list]:
        """Get WallStreetBets mention data."""
        return self._get("/live/wallstreetbets")

    def get_house_trades(self) -> Optional[list]:
        """Get recent House representative trades (Tier 1)."""
        return self._get("/live/housetrading")

    def get_senate_trades(self) -> Optional[list]:
        """Get recent Senate trades (Tier 1)."""
        return self._get("/live/senatetrading")

    def get_off_exchange(self) -> Optional[list]:
        """Get off-exchange / dark pool short volume data (Tier 1)."""
        return self._get("/live/offexchange")

    def get_flights(self) -> Optional[list]:
        """Get corporate flight tracking data (Tier 1)."""
        return self._get("/live/flights")

    def get_historical(self, dataset: str, ticker: str) -> Optional[list]:
        """Get historical data for a specific ticker."""
        return self._get(f"/historical/{dataset}/{ticker}")
