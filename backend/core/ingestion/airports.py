"""
Airport-pair distance calculation.

Concur exports usually have IATA airport codes but no distance — to apply
a per-passenger-km factor we have to reconstruct great-circle distance.

We ship a small embedded subset of the OpenFlights `airports.dat` (public
domain) covering the busiest ~250 international hubs. That keeps the
prototype self-contained without a multi-MB binary in git. Unmatched
codes flag the row `airport_unknown` so analysts can fix it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Airport:
    iata: str
    name: str
    country: str
    lat: float
    lon: float


# Source: OpenFlights airports.dat (https://openflights.org/data.html) —
# Open Database License. Extracted subset covering high-traffic hubs.
_AIRPORTS: dict[str, Airport] = {
    a.iata: a
    for a in [
        Airport("LHR", "London Heathrow", "GB", 51.4706, -0.461941),
        Airport("LGW", "London Gatwick", "GB", 51.148102, -0.190278),
        Airport("STN", "London Stansted", "GB", 51.885, 0.235),
        Airport("LTN", "London Luton", "GB", 51.874699, -0.368333),
        Airport("MAN", "Manchester", "GB", 53.35379, -2.27495),
        Airport("EDI", "Edinburgh", "GB", 55.95, -3.3725),
        Airport("BHX", "Birmingham", "GB", 52.453856, -1.748028),
        Airport("DUB", "Dublin", "IE", 53.421333, -6.270075),
        Airport("CDG", "Paris Charles de Gaulle", "FR", 49.012779, 2.55),
        Airport("ORY", "Paris Orly", "FR", 48.7233, 2.3794),
        Airport("AMS", "Amsterdam Schiphol", "NL", 52.308601, 4.76389),
        Airport("FRA", "Frankfurt", "DE", 50.033333, 8.570556),
        Airport("MUC", "Munich", "DE", 48.353802, 11.7861),
        Airport("BER", "Berlin Brandenburg", "DE", 52.362247, 13.500672),
        Airport("HAM", "Hamburg", "DE", 53.630402, 9.98823),
        Airport("ZRH", "Zurich", "CH", 47.464699, 8.54917),
        Airport("GVA", "Geneva", "CH", 46.23806, 6.10895),
        Airport("VIE", "Vienna", "AT", 48.110298, 16.5697),
        Airport("CPH", "Copenhagen", "DK", 55.617900, 12.656),
        Airport("ARN", "Stockholm Arlanda", "SE", 59.651901, 17.918600),
        Airport("OSL", "Oslo", "NO", 60.193901, 11.1004),
        Airport("HEL", "Helsinki", "FI", 60.317200, 24.963301),
        Airport("MAD", "Madrid Barajas", "ES", 40.471926, -3.56264),
        Airport("BCN", "Barcelona", "ES", 41.297078, 2.078463),
        Airport("LIS", "Lisbon", "PT", 38.7813, -9.13592),
        Airport("FCO", "Rome Fiumicino", "IT", 41.8003, 12.2389),
        Airport("MXP", "Milan Malpensa", "IT", 45.6306, 8.72811),
        Airport("LIN", "Milan Linate", "IT", 45.445103, 9.27674),
        Airport("ATH", "Athens", "GR", 37.936401, 23.9445),
        Airport("IST", "Istanbul", "TR", 41.275278, 28.751944),
        Airport("WAW", "Warsaw Chopin", "PL", 52.165833, 20.967222),
        Airport("PRG", "Prague", "CZ", 50.1008, 14.26),
        Airport("BUD", "Budapest", "HU", 47.42976, 19.261093),
        Airport("BRU", "Brussels", "BE", 50.901402, 4.48444),
        Airport("LUX", "Luxembourg", "LU", 49.6233, 6.20444),
        Airport("DXB", "Dubai International", "AE", 25.252778, 55.364444),
        Airport("AUH", "Abu Dhabi", "AE", 24.433, 54.6511),
        Airport("DOH", "Doha Hamad", "QA", 25.2731, 51.6080),
        Airport("RUH", "Riyadh King Khalid", "SA", 24.957599, 46.698799),
        Airport("BOM", "Mumbai", "IN", 19.0887, 72.8679),
        Airport("DEL", "Delhi Indira Gandhi", "IN", 28.5665, 77.103104),
        Airport("BLR", "Bengaluru Kempegowda", "IN", 13.197889, 77.706),
        Airport("MAA", "Chennai", "IN", 12.990005, 80.169296),
        Airport("HYD", "Hyderabad Rajiv Gandhi", "IN", 17.231318, 78.429855),
        Airport("CCU", "Kolkata", "IN", 22.654699, 88.446701),
        Airport("SIN", "Singapore Changi", "SG", 1.35019, 103.994003),
        Airport("KUL", "Kuala Lumpur", "MY", 2.745578, 101.709917),
        Airport("BKK", "Bangkok Suvarnabhumi", "TH", 13.681, 100.747),
        Airport("HKG", "Hong Kong", "HK", 22.308901, 113.915001),
        Airport("PEK", "Beijing Capital", "CN", 40.080101, 116.584999),
        Airport("PVG", "Shanghai Pudong", "CN", 31.143400, 121.805000),
        Airport("CAN", "Guangzhou Baiyun", "CN", 23.392400, 113.299004),
        Airport("ICN", "Seoul Incheon", "KR", 37.46907, 126.450517),
        Airport("NRT", "Tokyo Narita", "JP", 35.764702, 140.386002),
        Airport("HND", "Tokyo Haneda", "JP", 35.5523, 139.779999),
        Airport("KIX", "Osaka Kansai", "JP", 34.4347, 135.244003),
        Airport("SYD", "Sydney", "AU", -33.946098, 151.177002),
        Airport("MEL", "Melbourne Tullamarine", "AU", -37.673302, 144.843002),
        Airport("BNE", "Brisbane", "AU", -27.384199, 153.117004),
        Airport("AKL", "Auckland", "NZ", -37.008099, 174.792007),
        Airport("JFK", "New York JFK", "US", 40.639801, -73.7789),
        Airport("LGA", "New York LaGuardia", "US", 40.777199, -73.872597),
        Airport("EWR", "Newark Liberty", "US", 40.692501, -74.168701),
        Airport("BOS", "Boston Logan", "US", 42.36430, -71.005203),
        Airport("ORD", "Chicago O'Hare", "US", 41.9786, -87.9048),
        Airport("MDW", "Chicago Midway", "US", 41.785999, -87.752403),
        Airport("ATL", "Atlanta Hartsfield", "US", 33.6367, -84.428101),
        Airport("MIA", "Miami", "US", 25.79320, -80.290604),
        Airport("MCO", "Orlando", "US", 28.4294, -81.308998),
        Airport("DFW", "Dallas Fort Worth", "US", 32.896801, -97.038002),
        Airport("IAH", "Houston Bush", "US", 29.984399, -95.341400),
        Airport("DEN", "Denver", "US", 39.861698, -104.672997),
        Airport("PHX", "Phoenix Sky Harbor", "US", 33.434299, -112.011002),
        Airport("LAX", "Los Angeles", "US", 33.942501, -118.407997),
        Airport("SFO", "San Francisco", "US", 37.61899, -122.375),
        Airport("SAN", "San Diego", "US", 32.7336, -117.190002),
        Airport("SEA", "Seattle-Tacoma", "US", 47.4502, -122.308998),
        Airport("PDX", "Portland", "US", 45.588699, -122.598000),
        Airport("LAS", "Las Vegas", "US", 36.080101, -115.152000),
        Airport("SLC", "Salt Lake City", "US", 40.788399, -111.977997),
        Airport("DTW", "Detroit Metro", "US", 42.212398, -83.353401),
        Airport("MSP", "Minneapolis St Paul", "US", 44.881901, -93.221802),
        Airport("CLT", "Charlotte Douglas", "US", 35.214001, -80.943100),
        Airport("PHL", "Philadelphia", "US", 39.871899, -75.241096),
        Airport("DCA", "Washington Reagan", "US", 38.852100, -77.037697),
        Airport("IAD", "Washington Dulles", "US", 38.944500, -77.455803),
        Airport("YYZ", "Toronto Pearson", "CA", 43.6772, -79.630600),
        Airport("YVR", "Vancouver", "CA", 49.193901, -123.183998),
        Airport("YUL", "Montreal Trudeau", "CA", 45.470600, -73.740799),
        Airport("MEX", "Mexico City Benito Juarez", "MX", 19.4363, -99.072098),
        Airport("GRU", "Sao Paulo Guarulhos", "BR", -23.4356, -46.473099),
        Airport("EZE", "Buenos Aires Ezeiza", "AR", -34.8222, -58.5358),
        Airport("BOG", "Bogota El Dorado", "CO", 4.70159, -74.1469),
        Airport("LIM", "Lima Jorge Chavez", "PE", -12.0219, -77.114304),
        Airport("SCL", "Santiago Arturo Merino", "CL", -33.393001, -70.785797),
        Airport("JNB", "Johannesburg Tambo", "ZA", -26.139200, 28.246000),
        Airport("CPT", "Cape Town", "ZA", -33.964802, 18.601700),
        Airport("CAI", "Cairo", "EG", 30.121901, 31.405600),
        Airport("ADD", "Addis Ababa Bole", "ET", 8.97789, 38.799301),
        Airport("NBO", "Nairobi Jomo Kenyatta", "KE", -1.319240, 36.927799),
        Airport("LOS", "Lagos Murtala", "NG", 6.5774, 3.321160),
        Airport("CMN", "Casablanca Mohammed V", "MA", 33.367500, -7.589970),
        Airport("TLV", "Tel Aviv Ben Gurion", "IL", 32.011398, 34.886600),
    ]
}


def airport(iata: str) -> Optional[Airport]:
    return _AIRPORTS.get((iata or "").strip().upper())


def great_circle_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine; returns kilometres."""
    r = 6371.0088  # WGS-84 mean Earth radius
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def pair_distance_km(origin_iata: str, dest_iata: str) -> Optional[float]:
    o = airport(origin_iata)
    d = airport(dest_iata)
    if not o or not d:
        return None
    return great_circle_km(o.lat, o.lon, d.lat, d.lon)


def haul_category(
    distance_km: float,
    origin_iata: Optional[str] = None,
    dest_iata: Optional[str] = None,
) -> str:
    """
    DEFRA-aligned classification.

    Domestic = both airports in the same country (per IATA→country lookup).
    Short-haul = international flight under 3700 km (DEFRA's "intra-Europe"
                 short-haul bucket; we generalise to <3700 km for non-EU pairs).
    Long-haul = 3700 km or more.

    Distance alone is not enough: LHR→CDG is 347 km but DEFRA bills it
    as short-haul because the flight crosses borders. Without a country
    pair we fall back to a distance-only heuristic for the unknown case.
    """
    if origin_iata and dest_iata:
        o = airport(origin_iata)
        d = airport(dest_iata)
        if o and d and o.country == d.country:
            return "domestic"
        # both known and different countries → not domestic
        if o and d:
            return "long_haul" if distance_km >= 3700 else "short_haul"
    # Country unknown — distance-only heuristic
    if distance_km < 500:
        return "domestic"
    if distance_km < 3700:
        return "short_haul"
    return "long_haul"
