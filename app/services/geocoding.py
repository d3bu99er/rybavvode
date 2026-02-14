import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)


@dataclass
class GeocodeResult:
    lat: float
    lon: float
    confidence: float
    provider: str
    raw_address: str | None = None


class BaseGeocoder:
    provider_name: str

    async def geocode(self, place_name: str) -> GeocodeResult | None:
        raise NotImplementedError


class GoogleGeocoder(BaseGeocoder):
    provider_name = "google"

    LOCATION_TYPE_SCORE = {
        "ROOFTOP": 1.0,
        "RANGE_INTERPOLATED": 0.8,
        "GEOMETRIC_CENTER": 0.6,
        "APPROXIMATE": 0.4,
    }

    def __init__(self, api_key: str, timeout: int = 20):
        self.api_key = api_key
        self.timeout = timeout

    async def geocode(self, place_name: str) -> GeocodeResult | None:
        if not self.api_key:
            return None
        params = {"address": f"{place_name}, Россия", "key": self.api_key, "language": "ru"}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get("https://maps.googleapis.com/maps/api/geocode/json", params=params)
            resp.raise_for_status()
            payload = resp.json()
        if payload.get("status") != "OK" or not payload.get("results"):
            return None
        if len(payload["results"]) > 1:
            logger.info("Google geocoder returned %s candidates for '%s'", len(payload["results"]), place_name)
        best = sorted(
            payload["results"],
            key=lambda x: self.LOCATION_TYPE_SCORE.get(x.get("geometry", {}).get("location_type", "APPROXIMATE"), 0.1),
            reverse=True,
        )[0]
        loc = best["geometry"]["location"]
        confidence = self.LOCATION_TYPE_SCORE.get(best.get("geometry", {}).get("location_type", "APPROXIMATE"), 0.4)
        return GeocodeResult(lat=loc["lat"], lon=loc["lng"], confidence=confidence, provider=self.provider_name)


class YandexGeocoder(BaseGeocoder):
    provider_name = "yandex"

    PRECISION_SCORE = {
        "exact": 1.0,
        "number": 0.9,
        "near": 0.8,
        "street": 0.6,
        "other": 0.4,
    }

    def __init__(self, api_key: str, timeout: int = 20):
        self.api_key = api_key
        self.timeout = timeout

    async def geocode(self, place_name: str) -> GeocodeResult | None:
        if not self.api_key:
            return None
        params = {
            "apikey": self.api_key,
            "format": "json",
            "lang": "ru_RU",
            "results": 5,
            "geocode": f"{place_name}, Россия",
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get("https://geocode-maps.yandex.ru/1.x/", params=params)
            resp.raise_for_status()
            payload = resp.json()
        feature_members = payload.get("response", {}).get("GeoObjectCollection", {}).get("featureMember", [])
        if not feature_members:
            return None

        def score(feature):
            precision = (
                feature.get("GeoObject", {})
                .get("metaDataProperty", {})
                .get("GeocoderMetaData", {})
                .get("precision", "other")
            )
            return self.PRECISION_SCORE.get(precision, 0.3)

        if len(feature_members) > 1:
            logger.info("Yandex geocoder returned %s candidates for '%s'", len(feature_members), place_name)
        best = sorted(feature_members, key=score, reverse=True)[0]
        point = best["GeoObject"]["Point"]["pos"].split()
        lon, lat = float(point[0]), float(point[1])
        precision = best.get("GeoObject", {}).get("metaDataProperty", {}).get("GeocoderMetaData", {}).get("precision", "other")
        confidence = self.PRECISION_SCORE.get(precision, 0.4)
        return GeocodeResult(lat=lat, lon=lon, confidence=confidence, provider=self.provider_name)


class GeocodingService:
    def __init__(self, provider: BaseGeocoder):
        self.provider = provider

    async def geocode(self, place_name: str) -> GeocodeResult | None:
        return await self.provider.geocode(place_name)
