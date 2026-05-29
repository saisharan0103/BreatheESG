"""
Seed emission factors from real published sources.

Values are extracted from:
- DEFRA / UK DESNZ 2024 GHG conversion factors (condensed workbook v1.1,
  October 2024 correction): https://www.gov.uk/government/publications/greenhouse-gas-reporting-conversion-factors-2024
- US EPA Emission Factors Hub 2024 (uses eGRID 2022 data):
  https://www.epa.gov/climateleadership/ghg-emission-factors-hub

Every row carries its citation URL so SOURCES.md can be regenerated
from the database, and so auditors can verify each factor against the
original workbook.

Where DEFRA publishes values in fractional kg with many decimals, we
preserve 4-6 decimal places. Activity_type keys are the canonical names
used by the parsers in core/ingestion/.
"""
from django.db import migrations


DEFRA_URL = (
    "https://www.gov.uk/government/publications/greenhouse-gas-reporting-"
    "conversion-factors-2024"
)
EPA_URL = "https://www.epa.gov/climateleadership/ghg-emission-factors-hub"


FACTORS: list[dict] = [
    # ---- DEFRA 2024 — Scope 1 stationary + mobile combustion (liquid fuels) ----
    {
        "activity_type": "diesel",
        "scope": 1,
        "region": "GB",
        "year": 2024,
        "source": "defra",
        "unit": "litre",
        "kg_co2e_per_unit": "2.51233",
        "citation_url": DEFRA_URL,
        "citation_sheet": "Fuels — Liquid fuels — Diesel (average biofuel blend), total kg CO2e per litre",
        "notes": "Average biofuel-blended diesel in the UK retail mix.",
    },
    {
        "activity_type": "petrol",
        "scope": 1,
        "region": "GB",
        "year": 2024,
        "source": "defra",
        "unit": "litre",
        "kg_co2e_per_unit": "2.08660",
        "citation_url": DEFRA_URL,
        "citation_sheet": "Fuels — Liquid fuels — Petrol (average biofuel blend), kg CO2e per litre",
        "notes": "",
    },
    {
        "activity_type": "heating_oil",
        "scope": 1,
        "region": "GB",
        "year": 2024,
        "source": "defra",
        "unit": "litre",
        "kg_co2e_per_unit": "2.54603",
        "citation_url": DEFRA_URL,
        "citation_sheet": "Fuels — Liquid fuels — Burning oil",
        "notes": "Kerosene / domestic heating oil.",
    },
    {
        "activity_type": "lpg",
        "scope": 1,
        "region": "GB",
        "year": 2024,
        "source": "defra",
        "unit": "litre",
        "kg_co2e_per_unit": "1.55713",
        "citation_url": DEFRA_URL,
        "citation_sheet": "Fuels — Liquid fuels — LPG",
        "notes": "Liquefied petroleum gas / propane.",
    },
    # ---- DEFRA 2024 — Scope 1 gaseous fuels ----
    {
        "activity_type": "natural_gas",
        "scope": 1,
        "region": "GB",
        "year": 2024,
        "source": "defra",
        "unit": "kWh",
        "kg_co2e_per_unit": "0.18290",
        "citation_url": DEFRA_URL,
        "citation_sheet": "Fuels — Gaseous fuels — Natural gas (gross CV)",
        "notes": "Gross calorific value basis (matches UK supplier billing convention).",
    },
    # ---- DEFRA 2024 — Scope 2 electricity ----
    {
        "activity_type": "grid_electricity",
        "scope": 2,
        "region": "GB",
        "year": 2024,
        "source": "defra",
        "unit": "kWh",
        "kg_co2e_per_unit": "0.20705",
        "citation_url": DEFRA_URL,
        "citation_sheet": "UK electricity — generation (location-based, excluding T&D)",
        "notes": "Location-based Scope 2 generation factor. Add the T&D losses factor (Scope 3 cat 3) if reporting combined.",
    },
    # ---- DEFRA 2024 — Scope 3 business travel ----
    {
        "activity_type": "flight_domestic_economy",
        "scope": 3,
        "region": "GB",
        "year": 2024,
        "source": "defra",
        "unit": "passenger_km",
        "kg_co2e_per_unit": "0.24400",
        "citation_url": DEFRA_URL,
        "citation_sheet": "Business travel — air — Domestic, average passenger",
        "notes": "",
    },
    {
        "activity_type": "flight_short_haul_economy",
        "scope": 3,
        "region": "GB",
        "year": 2024,
        "source": "defra",
        "unit": "passenger_km",
        "kg_co2e_per_unit": "0.15100",
        "citation_url": DEFRA_URL,
        "citation_sheet": "Business travel — air — Short-haul economy",
        "notes": "DEFRA short-haul = flights within Europe.",
    },
    {
        "activity_type": "flight_short_haul_business",
        "scope": 3,
        "region": "GB",
        "year": 2024,
        "source": "defra",
        "unit": "passenger_km",
        "kg_co2e_per_unit": "0.22600",
        "citation_url": DEFRA_URL,
        "citation_sheet": "Business travel — air — Short-haul business",
        "notes": "",
    },
    {
        "activity_type": "flight_long_haul_economy",
        "scope": 3,
        "region": "GB",
        "year": 2024,
        "source": "defra",
        "unit": "passenger_km",
        "kg_co2e_per_unit": "0.14900",
        "citation_url": DEFRA_URL,
        "citation_sheet": "Business travel — air — Long-haul economy",
        "notes": "",
    },
    {
        "activity_type": "flight_long_haul_business",
        "scope": 3,
        "region": "GB",
        "year": 2024,
        "source": "defra",
        "unit": "passenger_km",
        "kg_co2e_per_unit": "0.43200",
        "citation_url": DEFRA_URL,
        "citation_sheet": "Business travel — air — Long-haul business",
        "notes": "",
    },
    {
        "activity_type": "flight_long_haul_first",
        "scope": 3,
        "region": "GB",
        "year": 2024,
        "source": "defra",
        "unit": "passenger_km",
        "kg_co2e_per_unit": "0.59600",
        "citation_url": DEFRA_URL,
        "citation_sheet": "Business travel — air — Long-haul first",
        "notes": "",
    },
    {
        "activity_type": "rail_national",
        "scope": 3,
        "region": "GB",
        "year": 2024,
        "source": "defra",
        "unit": "passenger_km",
        "kg_co2e_per_unit": "0.03549",
        "citation_url": DEFRA_URL,
        "citation_sheet": "Business travel — land — National rail",
        "notes": "",
    },
    # ---- DEFRA 2024 — hotel nights (country averages) ----
    {
        "activity_type": "hotel_night_gb",
        "scope": 3,
        "region": "GB",
        "year": 2024,
        "source": "defra",
        "unit": "room_night",
        "kg_co2e_per_unit": "10.40000",
        "citation_url": DEFRA_URL,
        "citation_sheet": "Hotel stay — United Kingdom",
        "notes": "kg CO2e per occupied room per night.",
    },
    {
        "activity_type": "hotel_night_us",
        "scope": 3,
        "region": "GB",
        "year": 2024,
        "source": "defra",
        "unit": "room_night",
        "kg_co2e_per_unit": "21.39000",
        "citation_url": DEFRA_URL,
        "citation_sheet": "Hotel stay — United States",
        "notes": "",
    },
    {
        "activity_type": "hotel_night_de",
        "scope": 3,
        "region": "GB",
        "year": 2024,
        "source": "defra",
        "unit": "room_night",
        "kg_co2e_per_unit": "14.95000",
        "citation_url": DEFRA_URL,
        "citation_sheet": "Hotel stay — Germany",
        "notes": "",
    },
    # Generic fallback for unknown country
    {
        "activity_type": "hotel_night",
        "scope": 3,
        "region": "GLOBAL",
        "year": 2024,
        "source": "defra",
        "unit": "room_night",
        "kg_co2e_per_unit": "15.00000",
        "citation_url": DEFRA_URL,
        "citation_sheet": "Hotel stay — global average derived from country list",
        "notes": "Used when country code can't be mapped; analyst should review.",
    },
    # ---- EPA 2024 — US factors ----
    {
        "activity_type": "diesel",
        "scope": 1,
        "region": "US",
        "year": 2024,
        "source": "epa",
        "unit": "litre",
        # 10.21 kg CO2 per US gallon ÷ 3.78541 L/gal = 2.69744
        "kg_co2e_per_unit": "2.69744",
        "citation_url": EPA_URL,
        "citation_sheet": "Table 2 — Mobile combustion CO2 — Distillate fuel oil no.2 (diesel)",
        "notes": "Converted from 10.21 kg CO2 per US gallon.",
    },
    {
        "activity_type": "petrol",
        "scope": 1,
        "region": "US",
        "year": 2024,
        "source": "epa",
        "unit": "litre",
        # 8.78 kg CO2 / US gallon ÷ 3.78541 = 2.31957
        "kg_co2e_per_unit": "2.31957",
        "citation_url": EPA_URL,
        "citation_sheet": "Table 2 — Mobile combustion CO2 — Motor gasoline",
        "notes": "Converted from 8.78 kg CO2 per US gallon (EPA inventory basis).",
    },
    {
        "activity_type": "natural_gas",
        "scope": 1,
        "region": "US",
        "year": 2024,
        "source": "epa",
        "unit": "kWh",
        # 53.06 kg CO2 / mmBtu = 53.06 / 293.071 kWh = 0.18105 (rounded)
        "kg_co2e_per_unit": "0.18105",
        "citation_url": EPA_URL,
        "citation_sheet": "Table 1 — Stationary combustion — Natural gas (commercial/industrial)",
        "notes": "Converted from 53.06 kg CO2 per mmBtu.",
    },
    {
        "activity_type": "grid_electricity",
        "scope": 2,
        "region": "US",
        "year": 2024,
        "source": "epa",
        "unit": "kWh",
        "kg_co2e_per_unit": "0.38700",
        "citation_url": EPA_URL,
        "citation_sheet": "Table 6 — Electricity (eGRID 2022) — US national average",
        "notes": "Use subregion factor when zip code/state is known; this is the national average.",
    },
    {
        "activity_type": "flight_short_haul_economy",
        "scope": 3,
        "region": "US",
        "year": 2024,
        "source": "epa",
        "unit": "passenger_km",
        # 0.207 kg per passenger-MILE ÷ 1.60934 = 0.12863
        "kg_co2e_per_unit": "0.12863",
        "citation_url": EPA_URL,
        "citation_sheet": "Table 8 — Business travel — Short-haul (<300 mi)",
        "notes": "Converted from EPA per-passenger-mile.",
    },
    {
        "activity_type": "flight_long_haul_economy",
        "scope": 3,
        "region": "US",
        "year": 2024,
        "source": "epa",
        "unit": "passenger_km",
        "kg_co2e_per_unit": "0.10128",
        "citation_url": EPA_URL,
        "citation_sheet": "Table 8 — Business travel — Long-haul (>2300 mi)",
        "notes": "Converted from 0.163 kg per passenger-mile.",
    },
]


def seed_factors(apps, schema_editor):
    EmissionFactor = apps.get_model("core", "EmissionFactor")
    for f in FACTORS:
        EmissionFactor.objects.update_or_create(
            activity_type=f["activity_type"],
            region=f["region"],
            year=f["year"],
            source=f["source"],
            defaults={
                "scope": f["scope"],
                "unit": f["unit"],
                "kg_co2e_per_unit": f["kg_co2e_per_unit"],
                "citation_url": f["citation_url"],
                "citation_sheet": f["citation_sheet"],
                "notes": f["notes"],
            },
        )


def unseed_factors(apps, schema_editor):
    EmissionFactor = apps.get_model("core", "EmissionFactor")
    for f in FACTORS:
        EmissionFactor.objects.filter(
            activity_type=f["activity_type"],
            region=f["region"],
            year=f["year"],
            source=f["source"],
        ).delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]
    operations = [migrations.RunPython(seed_factors, reverse_code=unseed_factors)]
