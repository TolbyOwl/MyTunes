from __future__ import annotations
import httpx
from typing import List, Optional
from mytunes.models.radio import RadioStation

# Open distributed radio-browser servers
RADIO_SERVERS = [
    "https://de1.api.radio-browser.info",
    "https://nl1.api.radio-browser.info",
    "https://at1.api.radio-browser.info"
]

class RadioProvider:
    """Interacts with the open Radio-Browser API to fetch 30,000+ worldwide radio stations."""

    def __init__(self):
        self.base_url = RADIO_SERVERS[0]
        self.client = httpx.Client(timeout=10.0, headers={"User-Agent": "MyTunes/1.0"})

    def get_top_stations(self, limit: int = 50) -> List[RadioStation]:
        """Fetches top-voted stations."""
        url = f"{self.base_url}/json/stations/topclick/{limit}"
        try:
            resp = self.client.get(url)
            if resp.status_code == 200:
                return self._parse_stations(resp.json())
        except Exception:
            pass
        return []

    def search_stations(
        self,
        name: Optional[str] = None,
        country: Optional[str] = None,
        tag: Optional[str] = None,
        limit: int = 50
    ) -> List[RadioStation]:
        """Searches stations by name, country, or musical genre/tag."""
        url = f"{self.base_url}/json/stations/search"
        params = {"limit": limit}
        if name:
            params["name"] = name
        if country:
            params["country"] = country
        if tag:
            params["tag"] = tag

        try:
            resp = self.client.get(url, params=params)
            if resp.status_code == 200:
                return self._parse_stations(resp.json())
        except Exception:
            pass
        return []

    def _parse_stations(self, data: list) -> List[RadioStation]:
        stations: List[RadioStation] = []
        for item in data:
            stream_url = item.get("url_resolved") or item.get("url")
            if not stream_url:
                continue
            stations.append(RadioStation(
                id=item.get("stationuuid", ""),
                name=item.get("name", "Unknown Station").strip(),
                stream_url=stream_url,
                homepage=item.get("homepage", ""),
                favicon=item.get("favicon") or None,
                country=item.get("country", ""),
                language=item.get("language", ""),
                tags=item.get("tags", ""),
                codec=item.get("codec", ""),
                bitrate=item.get("bitrate", 0)
            ))
        return stations
