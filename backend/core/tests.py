"""
Tests for the normalization layer.

The interesting bugs in ESG ingestion live in: locale-aware decimal
parsing, multi-format dates, unit conversion, and per-source header
quirks. Those are the only things tested here. Django/DRF plumbing is
not retested.
"""
from decimal import Decimal

from django.test import TestCase

from core.ingestion.airports import haul_category, pair_distance_km
from core.ingestion.common import normalize_quantity, parse_date, parse_decimal
from core.ingestion.sap import parse_sap_csv
from core.ingestion.travel import parse_travel_csv, parse_travel_json
from core.ingestion.utility_csv import parse_utility_csv


class ParseDecimalTests(TestCase):
    def test_plain_integer(self):
        self.assertEqual(parse_decimal("1234"), Decimal("1234"))

    def test_us_thousands_decimal(self):
        self.assertEqual(parse_decimal("1,234.56"), Decimal("1234.56"))

    def test_german_thousands_decimal(self):
        self.assertEqual(parse_decimal("1.234,56"), Decimal("1234.56"))

    def test_european_one_comma_short(self):
        # Ambiguous but obvious: "0,5" is half
        self.assertEqual(parse_decimal("0,5"), Decimal("0.5"))

    def test_european_one_comma_three_digits(self):
        # "1,234" in auto could go either way; auto picks "1.234" because
        # parts[0] is short and parts[1] is exactly 3 digits.
        self.assertEqual(parse_decimal("1,234"), Decimal("1.234"))

    def test_sap_german_four_decimal_price(self):
        # SAP exports prices with 4 decimal places (`1,4250`). In 'de'
        # locale the single comma is decimal regardless of count.
        self.assertEqual(parse_decimal("1,4250", locale_hint="de"), Decimal("1.4250"))

    def test_us_locale_strips_comma(self):
        self.assertEqual(parse_decimal("1,4250", locale_hint="us"), Decimal("14250"))

    def test_nbsp_thousands(self):
        # Some EU portals use non-breaking-space as thousands separator
        self.assertEqual(parse_decimal("1\xa0234,56"), Decimal("1234.56"))

    def test_empty_returns_none(self):
        self.assertIsNone(parse_decimal(""))
        self.assertIsNone(parse_decimal(None))

    def test_bad_string_returns_none(self):
        self.assertIsNone(parse_decimal("not a number"))


class ParseDateTests(TestCase):
    def test_sap_internal_yyyymmdd(self):
        d = parse_date("20240312")
        self.assertEqual(d.isoformat(), "2024-03-12")

    def test_iso_yyyymmdd(self):
        d = parse_date("2024-03-12")
        self.assertEqual(d.isoformat(), "2024-03-12")

    def test_german_ddmmyyyy(self):
        d = parse_date("12.03.2024", locale_hint="de")
        self.assertEqual(d.isoformat(), "2024-03-12")

    def test_us_slash(self):
        d = parse_date("03/12/2024", locale_hint="us")
        self.assertEqual(d.isoformat(), "2024-03-12")

    def test_uk_slash_dayfirst(self):
        d = parse_date("12/03/2024", locale_hint="uk")
        self.assertEqual(d.isoformat(), "2024-03-12")


class NormalizeQuantityTests(TestCase):
    def test_gallons_to_litres(self):
        n = normalize_quantity(Decimal("100"), "GAL")
        self.assertEqual(n.unit, "litre")
        self.assertAlmostEqual(float(n.quantity), 378.541, places=2)

    def test_mwh_to_kwh(self):
        n = normalize_quantity(Decimal("1.5"), "MWh")
        self.assertEqual(n.unit, "kWh")
        self.assertEqual(n.quantity, Decimal("1500"))

    def test_miles_to_km(self):
        n = normalize_quantity(Decimal("100"), "MI")
        self.assertEqual(n.unit, "km")
        self.assertAlmostEqual(float(n.quantity), 160.9344, places=2)

    def test_unknown_unit_with_default(self):
        n = normalize_quantity(Decimal("100"), "wat", default_canonical_unit="kWh")
        self.assertTrue(n.inferred)
        self.assertEqual(n.unit, "kWh")

    def test_unknown_unit_no_default(self):
        self.assertIsNone(normalize_quantity(Decimal("100"), "wat"))


class SapCsvParserTests(TestCase):
    EN_SAMPLE = (
        b"EBELN,EBELP,LIFNR,WERKS,MATNR,MATKL,MAKTX,MENGE,MEINS,NETWR,WAERS,BUDAT,BWART\n"
        b"4500000001,00010,V001,1000,300077,FUEL01,Diesel EN590,15000.000,L,21375.00,EUR,20240312,101\n"
        b"4500000002,00010,V001,1000,300078,FUEL_DIESEL,Diesel,200,L,300.00,EUR,20240315,101\n"
        # not a goods receipt — should be filtered
        b"4500000003,00010,V001,1000,300077,FUEL01,Diesel,10,L,20.00,EUR,20240316,201\n"
    )
    DE_SAMPLE = (
        "Einkaufsbeleg;Position;Lieferant;Werk;Material;Warengruppe;Materialkurztext;"
        "Menge;BME;Nettowert;Waehrung;Buchungsdatum;Bewegungsart\n"
        "4500000010;00010;V099;2000;300077;FUEL01;Diesel EN590 Tankware;"
        "15.000,000;L;21.375,00;EUR;12.03.2024;101\n"
    ).encode("utf-8")

    def test_english_headers(self):
        rows, errors, notes = parse_sap_csv(self.EN_SAMPLE)
        self.assertEqual(len(rows), 2)  # third row filtered (BWART != 101)
        self.assertEqual(errors, [])
        self.assertEqual(notes["delimiter"], ",")
        self.assertEqual(notes["locale_hint"], "us")
        self.assertEqual(rows[0].activity_type, "diesel")
        self.assertEqual(rows[0].quantity_canonical, Decimal("15000.000"))

    def test_german_headers(self):
        rows, errors, notes = parse_sap_csv(self.DE_SAMPLE)
        self.assertEqual(len(rows), 1)
        self.assertEqual(errors, [])
        self.assertEqual(notes["delimiter"], ";")
        self.assertEqual(notes["locale_hint"], "de")
        self.assertEqual(rows[0].quantity_canonical, Decimal("15000.000"))
        # The price field uses German number format; parser should not
        # have garbled it into 21375 thousand.
        self.assertEqual(rows[0].cost_amount, Decimal("21375.00"))

    def test_bwart_filter(self):
        # The not-101 row gets dropped silently (not an error).
        rows, errors, _ = parse_sap_csv(self.EN_SAMPLE)
        self.assertNotIn("00010", [r.raw.get("movement_type") for r in rows if r.raw.get("movement_type") == "201"])

    def test_gallons_unit(self):
        sample = (
            b"EBELN,EBELP,MATNR,MATKL,MAKTX,MENGE,MEINS,BUDAT,BWART\n"
            b"4500000050,00010,300077,FUEL01,Diesel,100,GAL,20240312,101\n"
        )
        rows, errs, _ = parse_sap_csv(sample)
        self.assertEqual(errs, [])
        self.assertEqual(rows[0].unit_canonical, "litre")
        self.assertAlmostEqual(float(rows[0].quantity_canonical), 378.5411784, places=3)


class UtilityCsvParserTests(TestCase):
    SAMPLE = (
        b"MPAN,SiteName,PeriodStart,PeriodEnd,UnitsConsumed_kWh,Tariff,EstimatedFlag\n"
        b"2000012345678,London HQ,2024-01-01,2024-01-31,52400,Fixed 24 Business,A\n"
        b"2000012345678,London HQ,2024-02-01,2024-02-29,48900,Fixed 24 Business,E\n"
    )

    def test_pascalcase_headers(self):
        rows, errors, _ = parse_utility_csv(self.SAMPLE)
        self.assertEqual(errors, [])
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].kwh, Decimal("52400"))
        self.assertFalse(rows[0].estimated)
        self.assertTrue(rows[1].estimated)

    def test_day_night_split_summing(self):
        sample = (
            b"MPAN,PeriodStart,PeriodEnd,DayUnitsKwh,NightUnitsKwh\n"
            b"2000012345678,2024-01-01,2024-01-31,30000,15000\n"
        )
        rows, errors, _ = parse_utility_csv(sample)
        self.assertEqual(errors, [])
        self.assertEqual(rows[0].kwh, Decimal("45000"))
        self.assertIn("kwh_summed_from_day_night", rows[0].parse_warnings)

    def test_invalid_period_rejected(self):
        sample = (
            b"MPAN,PeriodStart,PeriodEnd,UnitsConsumed_kWh\n"
            b"2000012345678,2024-02-01,2024-01-31,52400\n"  # reversed
        )
        rows, errors, _ = parse_utility_csv(sample)
        self.assertEqual(rows, [])
        self.assertTrue(any("before period_start" in e for e in errors))


class TravelParserTests(TestCase):
    SAMPLE = (
        b"Trip ID,Employee ID,Segment Type,Start Date,End Date,"
        b"Departure Airport Code,Arrival Airport Code,Cabin Class,"
        b"Distance in Miles,Hotel Name,Number of Nights,Country,"
        b"Total Amount,Currency Code\n"
        b"T1,E1,Air,2024-04-08,2024-04-08,LHR,JFK,J,,,,,,4280.50,USD\n"
        b"T1,E1,Hotel,2024-04-08,2024-04-12,,,,,Hilton Midtown,4,US,1156.00,USD\n"
        b"T2,E1,Air,2024-04-15,2024-04-15,LHR,CDG,Y,,,,,,245.00,EUR\n"
    )

    def test_concur_style_csv(self):
        rows, errors, _ = parse_travel_csv(self.SAMPLE)
        self.assertEqual(errors, [])
        self.assertEqual(len(rows), 3)

    def test_flight_distance_reconstructed_from_iata(self):
        rows, _, _ = parse_travel_csv(self.SAMPLE)
        lhr_jfk = rows[0]
        self.assertEqual(lhr_jfk.unit, "passenger_km")
        self.assertGreater(float(lhr_jfk.quantity), 5000)  # ~5540 km
        self.assertLess(float(lhr_jfk.quantity), 6000)
        self.assertEqual(lhr_jfk.activity_type, "flight_long_haul_business")

    def test_short_haul_classification_uses_country(self):
        # LHR->CDG is 347 km — distance-only would say domestic; country
        # comparison says short-haul because GB != FR.
        rows, _, _ = parse_travel_csv(self.SAMPLE)
        lhr_cdg = rows[2]
        self.assertEqual(lhr_cdg.activity_type, "flight_short_haul_economy")

    def test_hotel_nights_used(self):
        rows, _, _ = parse_travel_csv(self.SAMPLE)
        hotel = rows[1]
        self.assertEqual(hotel.unit, "room_night")
        self.assertEqual(hotel.quantity, Decimal("4"))
        self.assertEqual(hotel.activity_type, "hotel_night_us")

    def test_json_array_shape(self):
        payload = (
            b'[{"trip_id":"T1","employee_id":"E1","segment_type":"air",'
            b'"start_date":"2024-04-08","origin_iata":"LHR",'
            b'"destination_iata":"FRA","cabin_class":"Y"}]'
        )
        rows, errors, notes = parse_travel_json(payload)
        self.assertEqual(errors, [])
        self.assertEqual(len(rows), 1)
        self.assertEqual(notes["shape"], "array_of_segments")
        # LHR->FRA ~660 km, different countries → short_haul
        self.assertEqual(rows[0].activity_type, "flight_short_haul_economy")


class AirportTests(TestCase):
    def test_known_pair_distance(self):
        km = pair_distance_km("LHR", "JFK")
        self.assertIsNotNone(km)
        self.assertAlmostEqual(km, 5536, delta=50)

    def test_unknown_pair_returns_none(self):
        self.assertIsNone(pair_distance_km("LHR", "ZZZ"))

    def test_haul_domestic_same_country(self):
        # MAN->LHR is ~260 km AND both GB
        self.assertEqual(haul_category(260, "MAN", "LHR"), "domestic")

    def test_haul_short_haul_cross_border(self):
        # LHR->CDG: 347 km, GB vs FR → short_haul
        self.assertEqual(haul_category(347, "LHR", "CDG"), "short_haul")

    def test_haul_long_haul(self):
        self.assertEqual(haul_category(5500, "LHR", "JFK"), "long_haul")
