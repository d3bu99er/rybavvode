import pytest

from app.services.geocoding import BaseGeocoder, GeocodeResult, GeocodingService


class FakeGeocoder(BaseGeocoder):
    provider_name = "fake"

    async def geocode(self, place_name: str):
        return GeocodeResult(lat=10.0, lon=20.0, confidence=0.7, provider=self.provider_name)


@pytest.mark.asyncio
async def test_geocoding_service_mock():
    service = GeocodingService(FakeGeocoder())
    result = await service.geocode("Test")
    assert result is not None
    assert result.provider == "fake"
    assert result.lat == 10.0
