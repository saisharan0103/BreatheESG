"""Local smoke test: run ingestion against real-shape sample bytes."""
import os
import sys
import django

# Force stdout to UTF-8 on Windows so DEFRA/IATA arrows etc. don't break.
sys.stdout.reconfigure(encoding="utf-8")

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "breatheesg.settings")
django.setup()

from core.ingestion.sap import parse_sap_csv
from core.ingestion.utility_csv import parse_utility_csv
from core.ingestion.travel import parse_travel_csv, parse_travel_json
from core.ingestion.airports import pair_distance_km
from core.ingestion.common import find_emission_factor
from core.models import EmissionFactor


print("=" * 60)
print("Emission factors loaded:")
for f in EmissionFactor.objects.all().order_by("region", "activity_type", "year"):
    print(f"  {f.region} {f.activity_type} {f.year} = {f.kg_co2e_per_unit} kg CO2e/{f.unit}")


print("=" * 60)
print("SAP English CSV:")
sap_en = b"""EBELN,EBELP,LIFNR,WERKS,LGORT,MATNR,MAKTX,MATKL,MENGE,MEINS,NETPR,PEINH,NETWR,WAERS,BUDAT,KOSTL,BWART
4500001234,00010,V100245,1000,F001,000000000000300077,Diesel EN590 bulk,FUEL01,15000.000,L,1.4250,1,21375.00,EUR,20240312,CC-DE-LOG-01,101
4500001234,00020,V100245,1000,F001,000000000000300078,Adblue 32.5%,FUEL02,500.000,L,0.7800,1,390.00,EUR,20240312,CC-DE-LOG-01,101
4500001288,00010,V100502,2000,F003,000000000000300077,Diesel EN590 bulk,FUEL01,8200.000,L,1.4810,1,12144.20,EUR,20240318,CC-FR-LOG-01,101
"""
rows, errs, notes = parse_sap_csv(sap_en)
print(f"rows={len(rows)} errors={len(errs)} notes={notes}")
for r in rows:
    print(f"  {r.source_record_id} {r.activity_type} {r.quantity_canonical} {r.unit_canonical} {r.posting_date}")

print("=" * 60)
print("SAP German CSV (semicolon, DE numbers):")
sap_de = (
    "Einkaufsbeleg;Position;Lieferant;Werk;Lagerort;Material;Materialkurztext;"
    "Warengruppe;Menge;BME;Nettopreis;Preiseinheit;Nettowert;Waehrung;"
    "Buchungsdatum;Kostenstelle;Bewegungsart\n"
    "4500001234;00010;V100245;1000;F001;000000000000300077;Diesel EN590 Tankware;"
    "FUEL01;15.000,000;L;1,4250;1;21.375,00;EUR;12.03.2024;CC-DE-LOG-01;101\n"
    "4500001234;00020;V100245;1000;F001;000000000000300078;Adblue 32,5%;"
    "FUEL02;500,000;L;0,7800;1;390,00;EUR;12.03.2024;CC-DE-LOG-01;101\n"
).encode("utf-8")
rows, errs, notes = parse_sap_csv(sap_de)
print(f"rows={len(rows)} errors={len(errs)} notes={notes}")
for r in rows:
    print(f"  {r.source_record_id} {r.activity_type} {r.quantity_canonical} {r.unit_canonical} {r.posting_date}")

print("=" * 60)
print("Utility CSV:")
util = b"""MPAN,Site,PeriodStart,PeriodEnd,UnitsConsumed_kWh,Tariff,EstimatedFlag
2000012345678,London HQ,2024-01-01,2024-01-31,52400,Fixed 24 Business,A
2000012345678,London HQ,2024-02-01,2024-02-29,48900,Fixed 24 Business,A
2000012345679,Manchester DC,2024-01-01,2024-01-31,128300,HH Variable,E
"""
rows, errs, notes = parse_utility_csv(util)
print(f"rows={len(rows)} errors={len(errs)} notes={notes}")
for r in rows:
    print(f"  {r.meter_id} {r.kwh} kWh {r.period_start}..{r.period_end} estimated={r.estimated}")

print("=" * 60)
print("Travel CSV (Concur-style):")
travel = b"""Trip ID,Employee ID,Segment Type,Start Date,End Date,Departure Airport Code,Arrival Airport Code,Cabin Class,Distance in Miles,Hotel Name,Number of Nights,Country,Total Amount,Currency Code
T-4471290,E10245,Air,2024-04-08,2024-04-08,LHR,JFK,J,,,,,,4280.50,USD
T-4471290,E10245,Hotel,2024-04-08,2024-04-12,,,,,Hilton Midtown,4,US,1156.00,USD
T-4471291,E10245,Air,2024-04-15,2024-04-15,LHR,CDG,Y,,,,,,245.00,EUR
"""
rows, errs, notes = parse_travel_csv(travel)
print(f"rows={len(rows)} errors={len(errs)} notes={notes}")
for r in rows:
    print(f"  {r.segment_type} {r.activity_type} {r.quantity} {r.unit} | {r.description}")

print("=" * 60)
print("Airport distance check: LHR->JFK")
print(f"  {pair_distance_km('LHR', 'JFK'):.1f} km (expected ~5536)")

print("=" * 60)
print("Factor lookup: diesel in GB 2024 ->", find_emission_factor("diesel", "GB", 2024))
print("Factor lookup: diesel in US 2024 ->", find_emission_factor("diesel", "US", 2024))
print("Factor lookup: grid_electricity in GB 2024 ->", find_emission_factor("grid_electricity", "GB", 2024))
print("Factor lookup: flight_long_haul_business in GB 2024 ->", find_emission_factor("flight_long_haul_business", "GB", 2024))
print("Factor lookup: hotel_night_us in GB 2024 ->", find_emission_factor("hotel_night_us", "GB", 2024))
