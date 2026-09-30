#!/usr/bin/env python3
"""Regenerate logbook/tables/airports.csv from OurAirports (public domain).

    uv run python scripts/make_airports.py [airports.csv]

Downloads https://davidmegginson.github.io/ourairports-data/airports.csv (or reads the file given),
keeps every `large_airport` with scheduled service and both an IATA and an ICAO code — the world's
major airports, about 1,150 of them — and writes `iata,icao,name,lat,lon,tz`, sorted by IATA.

OurAirports has no timezone; the IANA zone comes from the maps below: one zone per country, and per
region for the countries that span several. Every zone is checked against the zone database before
it is written. This is a development script: it is the only place flights code touches the network,
and it is never run by the CLI (CLAUDE.md: no network on an adapter's default path).
"""

from __future__ import annotations

import csv
import io
import sys
import urllib.request
import zoneinfo
from pathlib import Path

URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"
OUT = Path(__file__).resolve().parents[1] / "logbook" / "tables" / "airports.csv"
HEADER = (
    "# OurAirports (public domain), large airports with scheduled service;"
    " tz assigned by scripts/make_airports.py\n"
)

# ISO 3166-1 alpha-2 → IANA zone, for countries with one zone (or one that covers every large airport).
COUNTRY = {
    "AD": "Europe/Andorra", "AE": "Asia/Dubai", "AF": "Asia/Kabul", "AG": "America/Antigua",
    "AI": "America/Anguilla", "AL": "Europe/Tirane", "AM": "Asia/Yerevan", "AO": "Africa/Luanda",
    "AR": "America/Argentina/Buenos_Aires", "AS": "Pacific/Pago_Pago", "AT": "Europe/Vienna",
    "AW": "America/Aruba", "AZ": "Asia/Baku", "BA": "Europe/Sarajevo", "BB": "America/Barbados",
    "BD": "Asia/Dhaka", "BE": "Europe/Brussels", "BF": "Africa/Ouagadougou", "BG": "Europe/Sofia",
    "BH": "Asia/Bahrain", "BI": "Africa/Bujumbura", "BJ": "Africa/Porto-Novo", "BM": "Atlantic/Bermuda",
    "BN": "Asia/Brunei", "BO": "America/La_Paz", "BQ": "America/Kralendijk", "BS": "America/Nassau",
    "BT": "Asia/Thimphu", "BW": "Africa/Gaborone", "BY": "Europe/Minsk", "BZ": "America/Belize",
    "CC": "Indian/Cocos", "CF": "Africa/Bangui", "CG": "Africa/Brazzaville", "CH": "Europe/Zurich",
    "CI": "Africa/Abidjan", "CK": "Pacific/Rarotonga", "CM": "Africa/Douala", "CN": "Asia/Shanghai",
    "CO": "America/Bogota", "CR": "America/Costa_Rica", "CU": "America/Havana", "CV": "Atlantic/Cape_Verde",
    "CW": "America/Curacao", "CY": "Asia/Nicosia", "CZ": "Europe/Prague", "DE": "Europe/Berlin",
    "DJ": "Africa/Djibouti", "DK": "Europe/Copenhagen", "DM": "America/Dominica",
    "DO": "America/Santo_Domingo",
    "DZ": "Africa/Algiers", "EE": "Europe/Tallinn", "EG": "Africa/Cairo", "EH": "Africa/El_Aaiun",
    "ER": "Africa/Asmara", "ET": "Africa/Addis_Ababa", "FI": "Europe/Helsinki", "FJ": "Pacific/Fiji",
    "FO": "Atlantic/Faroe", "FR": "Europe/Paris", "GA": "Africa/Libreville", "GB": "Europe/London",
    "GD": "America/Grenada", "GE": "Asia/Tbilisi", "GF": "America/Cayenne", "GG": "Europe/Guernsey",
    "GH": "Africa/Accra", "GI": "Europe/Gibraltar", "GL": "America/Nuuk", "GM": "Africa/Banjul",
    "GN": "Africa/Conakry", "GP": "America/Guadeloupe", "GQ": "Africa/Malabo", "GR": "Europe/Athens",
    "GT": "America/Guatemala", "GU": "Pacific/Guam", "GW": "Africa/Bissau", "GY": "America/Guyana",
    "HK": "Asia/Hong_Kong", "HN": "America/Tegucigalpa", "HR": "Europe/Zagreb",
    "HT": "America/Port-au-Prince",
    "HU": "Europe/Budapest", "IE": "Europe/Dublin", "IL": "Asia/Jerusalem", "IM": "Europe/Isle_of_Man",
    "IN": "Asia/Kolkata", "IQ": "Asia/Baghdad", "IR": "Asia/Tehran", "IS": "Atlantic/Reykjavik",
    "IT": "Europe/Rome", "JE": "Europe/Jersey", "JM": "America/Jamaica", "JO": "Asia/Amman",
    "JP": "Asia/Tokyo", "KE": "Africa/Nairobi", "KG": "Asia/Bishkek", "KH": "Asia/Phnom_Penh",
    "KM": "Indian/Comoro", "KN": "America/St_Kitts", "KP": "Asia/Pyongyang", "KR": "Asia/Seoul",
    "KW": "Asia/Kuwait", "KY": "America/Cayman", "KZ": "Asia/Almaty", "LA": "Asia/Vientiane",
    "LB": "Asia/Beirut", "LC": "America/St_Lucia", "LI": "Europe/Vaduz", "LK": "Asia/Colombo",
    "LR": "Africa/Monrovia", "LS": "Africa/Maseru", "LT": "Europe/Vilnius", "LU": "Europe/Luxembourg",
    "LV": "Europe/Riga", "LY": "Africa/Tripoli", "MA": "Africa/Casablanca", "MC": "Europe/Monaco",
    "MD": "Europe/Chisinau", "ME": "Europe/Podgorica", "MG": "Indian/Antananarivo", "MH": "Pacific/Majuro",
    "MK": "Europe/Skopje", "ML": "Africa/Bamako", "MM": "Asia/Yangon", "MN": "Asia/Ulaanbaatar",
    "MO": "Asia/Macau", "MP": "Pacific/Saipan", "MQ": "America/Martinique", "MR": "Africa/Nouakchott",
    "MS": "America/Montserrat", "MT": "Europe/Malta", "MU": "Indian/Mauritius", "MV": "Indian/Maldives",
    "MW": "Africa/Blantyre", "MY": "Asia/Kuala_Lumpur", "MZ": "Africa/Maputo", "NA": "Africa/Windhoek",
    "NC": "Pacific/Noumea", "NE": "Africa/Niamey", "NG": "Africa/Lagos", "NI": "America/Managua",
    "NL": "Europe/Amsterdam", "NO": "Europe/Oslo", "NP": "Asia/Kathmandu", "NR": "Pacific/Nauru",
    "NU": "Pacific/Niue", "NZ": "Pacific/Auckland", "OM": "Asia/Muscat", "PA": "America/Panama",
    "PE": "America/Lima", "PF": "Pacific/Tahiti", "PH": "Asia/Manila", "PK": "Asia/Karachi",
    "PL": "Europe/Warsaw", "PR": "America/Puerto_Rico", "PS": "Asia/Gaza", "PW": "Pacific/Palau",
    "PY": "America/Asuncion", "QA": "Asia/Qatar", "RE": "Indian/Reunion", "RO": "Europe/Bucharest",
    "RS": "Europe/Belgrade", "RW": "Africa/Kigali", "SA": "Asia/Riyadh", "SB": "Pacific/Guadalcanal",
    "SC": "Indian/Mahe", "SD": "Africa/Khartoum", "SE": "Europe/Stockholm", "SG": "Asia/Singapore",
    "SI": "Europe/Ljubljana", "SK": "Europe/Bratislava", "SL": "Africa/Freetown", "SM": "Europe/San_Marino",
    "SN": "Africa/Dakar", "SO": "Africa/Mogadishu", "SR": "America/Paramaribo", "SS": "Africa/Juba",
    "ST": "Africa/Sao_Tome", "SV": "America/El_Salvador", "SX": "America/Lower_Princes",
    "SY": "Asia/Damascus",
    "SZ": "Africa/Mbabane", "TC": "America/Grand_Turk", "TD": "Africa/Ndjamena", "TG": "Africa/Lome",
    "TH": "Asia/Bangkok", "TJ": "Asia/Dushanbe", "TL": "Asia/Dili", "TM": "Asia/Ashgabat",
    "TN": "Africa/Tunis", "TO": "Pacific/Tongatapu", "TR": "Europe/Istanbul", "TT": "America/Port_of_Spain",
    "TV": "Pacific/Funafuti", "TW": "Asia/Taipei", "TZ": "Africa/Dar_es_Salaam", "UA": "Europe/Kyiv",
    "UG": "Africa/Kampala", "UY": "America/Montevideo", "UZ": "Asia/Tashkent", "VC": "America/St_Vincent",
    "VE": "America/Caracas", "VG": "America/Tortola", "VI": "America/St_Thomas", "VN": "Asia/Ho_Chi_Minh",
    "VU": "Pacific/Efate", "WF": "Pacific/Wallis", "WS": "Pacific/Apia", "XK": "Europe/Belgrade",
    "YE": "Asia/Aden", "YT": "Indian/Mayotte", "ZA": "Africa/Johannesburg", "ZM": "Africa/Lusaka",
    "ZW": "Africa/Harare",
    # countries with several zones: the mainland default; REGION below overrides the rest
    "ES": "Europe/Madrid", "PT": "Europe/Lisbon", "MX": "America/Mexico_City", "CL": "America/Santiago",
    "EC": "America/Guayaquil", "PG": "Pacific/Port_Moresby", "CD": "Africa/Kinshasa",
}  # fmt: skip

# ISO 3166-2 region → zone, for countries with several zones. A region missing here falls back to
# the country's entry above, if any; else the airport is left out and named on stderr.
REGION = {
    # United States
    "US-AK": "America/Anchorage", "US-AL": "America/Chicago", "US-AR": "America/Chicago",
    "US-AZ": "America/Phoenix", "US-CA": "America/Los_Angeles", "US-CO": "America/Denver",
    "US-CT": "America/New_York", "US-DC": "America/New_York", "US-DE": "America/New_York",
    "US-FL": "America/New_York", "US-GA": "America/New_York", "US-HI": "Pacific/Honolulu",
    "US-IA": "America/Chicago", "US-ID": "America/Boise", "US-IL": "America/Chicago",
    "US-IN": "America/Indiana/Indianapolis", "US-KS": "America/Chicago", "US-KY": "America/New_York",
    "US-LA": "America/Chicago", "US-MA": "America/New_York", "US-MD": "America/New_York",
    "US-ME": "America/New_York", "US-MI": "America/Detroit", "US-MN": "America/Chicago",
    "US-MO": "America/Chicago", "US-MS": "America/Chicago", "US-MT": "America/Denver",
    "US-NC": "America/New_York", "US-ND": "America/Chicago", "US-NE": "America/Chicago",
    "US-NH": "America/New_York", "US-NJ": "America/New_York", "US-NM": "America/Denver",
    "US-NV": "America/Los_Angeles", "US-NY": "America/New_York", "US-OH": "America/New_York",
    "US-OK": "America/Chicago", "US-OR": "America/Los_Angeles", "US-PA": "America/New_York",
    "US-RI": "America/New_York", "US-SC": "America/New_York", "US-SD": "America/Chicago",
    "US-TN": "America/Chicago", "US-TX": "America/Chicago", "US-UT": "America/Denver",
    "US-VA": "America/New_York", "US-VT": "America/New_York", "US-WA": "America/Los_Angeles",
    "US-WI": "America/Chicago", "US-WV": "America/New_York", "US-WY": "America/Denver",
    # Canada
    "CA-AB": "America/Edmonton", "CA-BC": "America/Vancouver", "CA-MB": "America/Winnipeg",
    "CA-NB": "America/Moncton", "CA-NL": "America/St_Johns", "CA-NS": "America/Halifax",
    "CA-NT": "America/Yellowknife", "CA-NU": "America/Iqaluit", "CA-ON": "America/Toronto",
    "CA-PE": "America/Halifax", "CA-QC": "America/Toronto", "CA-SK": "America/Regina",
    "CA-YT": "America/Whitehorse",
    # Australia
    "AU-ACT": "Australia/Sydney", "AU-NSW": "Australia/Sydney", "AU-NT": "Australia/Darwin",
    "AU-QLD": "Australia/Brisbane", "AU-SA": "Australia/Adelaide", "AU-TAS": "Australia/Hobart",
    "AU-VIC": "Australia/Melbourne", "AU-WA": "Australia/Perth",
    # Brazil
    "BR-AC": "America/Rio_Branco", "BR-AL": "America/Maceio", "BR-AM": "America/Manaus",
    "BR-AP": "America/Belem", "BR-BA": "America/Bahia", "BR-CE": "America/Fortaleza",
    "BR-DF": "America/Sao_Paulo", "BR-ES": "America/Sao_Paulo", "BR-GO": "America/Sao_Paulo",
    "BR-MA": "America/Fortaleza", "BR-MG": "America/Sao_Paulo", "BR-MS": "America/Campo_Grande",
    "BR-MT": "America/Cuiaba", "BR-PA": "America/Belem", "BR-PB": "America/Fortaleza",
    "BR-PE": "America/Recife", "BR-PI": "America/Fortaleza", "BR-PR": "America/Sao_Paulo",
    "BR-RJ": "America/Sao_Paulo", "BR-RN": "America/Fortaleza", "BR-RO": "America/Porto_Velho",
    "BR-RR": "America/Boa_Vista", "BR-RS": "America/Sao_Paulo", "BR-SC": "America/Sao_Paulo",
    "BR-SE": "America/Maceio", "BR-SP": "America/Sao_Paulo", "BR-TO": "America/Araguaina",
    # Mexico
    "MX-BCN": "America/Tijuana", "MX-BCS": "America/Mazatlan", "MX-CHH": "America/Chihuahua",
    "MX-NAY": "America/Bahia_Banderas", "MX-ROO": "America/Cancun", "MX-SIN": "America/Mazatlan",
    "MX-SON": "America/Hermosillo",
    # Russia
    "RU-ALT": "Asia/Barnaul", "RU-AST": "Europe/Astrakhan", "RU-BA": "Asia/Yekaterinburg",
    "RU-BU": "Asia/Irkutsk", "RU-CE": "Europe/Moscow", "RU-CHE": "Asia/Yekaterinburg",
    "RU-DA": "Europe/Moscow", "RU-IRK": "Asia/Irkutsk", "RU-KAM": "Asia/Kamchatka",
    "RU-KDA": "Europe/Moscow", "RU-KEM": "Asia/Novokuznetsk", "RU-KGD": "Europe/Kaliningrad",
    "RU-KHM": "Asia/Yekaterinburg", "RU-KK": "Asia/Krasnoyarsk", "RU-KYA": "Asia/Krasnoyarsk",
    "RU-MO": "Europe/Moscow", "RU-MOS": "Europe/Moscow", "RU-MOW": "Europe/Moscow",
    "RU-MUR": "Europe/Moscow", "RU-NIZ": "Europe/Moscow", "RU-NVS": "Asia/Novosibirsk",
    "RU-OMS": "Asia/Omsk", "RU-PER": "Asia/Yekaterinburg", "RU-PRI": "Asia/Vladivostok",
    "RU-SA": "Asia/Yakutsk", "RU-SAK": "Asia/Sakhalin", "RU-SAM": "Europe/Samara",
    "RU-SAR": "Europe/Saratov", "RU-SPE": "Europe/Moscow", "RU-STA": "Europe/Moscow",
    "RU-SVE": "Asia/Yekaterinburg", "RU-TA": "Europe/Moscow", "RU-TOM": "Asia/Tomsk",
    "RU-TYU": "Asia/Yekaterinburg", "RU-VGG": "Europe/Volgograd", "RU-YAR": "Europe/Moscow",
    "RU-ZAB": "Asia/Chita", "RU-KHA": "Asia/Vladivostok", "RU-MAG": "Asia/Magadan",
    "RU-ULY": "Europe/Ulyanovsk", "RU-UD": "Europe/Samara", "RU-ORE": "Asia/Yekaterinburg",
    "RU-KGN": "Asia/Yekaterinburg", "RU-TY": "Asia/Krasnoyarsk", "RU-KL": "Europe/Moscow",
    "RU-ARK": "Europe/Moscow", "RU-KO": "Europe/Moscow", "RU-YAN": "Asia/Yekaterinburg",
    "RU-CU": "Europe/Moscow", "RU-ME": "Europe/Moscow", "RU-VLA": "Europe/Moscow",
    # Indonesia: west (Jakarta), central (Makassar), east (Jayapura)
    "ID-AC": "Asia/Jakarta", "ID-BA": "Asia/Makassar", "ID-BB": "Asia/Jakarta", "ID-BE": "Asia/Jakarta",
    "ID-BT": "Asia/Jakarta", "ID-GO": "Asia/Makassar", "ID-JA": "Asia/Jakarta", "ID-JB": "Asia/Jakarta",
    "ID-JI": "Asia/Jakarta", "ID-JK": "Asia/Jakarta", "ID-JT": "Asia/Jakarta", "ID-KB": "Asia/Jakarta",
    "ID-KI": "Asia/Makassar", "ID-KR": "Asia/Jakarta", "ID-KS": "Asia/Makassar", "ID-KT": "Asia/Jakarta",
    "ID-KU": "Asia/Makassar", "ID-LA": "Asia/Jakarta", "ID-MA": "Asia/Jayapura", "ID-MU": "Asia/Jayapura",
    "ID-NB": "Asia/Makassar", "ID-NT": "Asia/Makassar", "ID-PA": "Asia/Jayapura", "ID-PB": "Asia/Jayapura",
    "ID-RI": "Asia/Jakarta", "ID-SA": "Asia/Makassar", "ID-SB": "Asia/Jakarta", "ID-SG": "Asia/Makassar",
    "ID-SN": "Asia/Makassar", "ID-SR": "Asia/Makassar", "ID-SS": "Asia/Jakarta", "ID-ST": "Asia/Makassar",
    "ID-SU": "Asia/Jakarta", "ID-YO": "Asia/Jakarta",
    # Chile, Spain, Portugal, Ecuador, Kiribati, Micronesia, Papua New Guinea, DR Congo
    "CL-MA": "America/Punta_Arenas", "CL-VS": "America/Santiago",
    "ES-CN": "Atlantic/Canary",
    "PT-20": "Atlantic/Azores", "PT-30": "Atlantic/Madeira",
    "EC-W": "Pacific/Galapagos",
    "KI-G": "Pacific/Tarawa", "KI-L": "Pacific/Kiritimati", "KI-P": "Pacific/Kanton",
    "FM-KSA": "Pacific/Kosrae", "FM-PNI": "Pacific/Pohnpei", "FM-TRK": "Pacific/Chuuk",
    "FM-YAP": "Pacific/Chuuk",
    "PG-NSB": "Pacific/Bougainville",
    "CD-KN": "Africa/Kinshasa", "CD-KC": "Africa/Kinshasa", "CD-EQ": "Africa/Kinshasa",
    "CD-HK": "Africa/Lubumbashi", "CD-NK": "Africa/Lubumbashi", "CD-TO": "Africa/Lubumbashi",
    "CD-SK": "Africa/Lubumbashi", "CD-KE": "Africa/Lubumbashi",
    # Mongolia west, Greenland
    "MN-071": "Asia/Hovd", "MN-065": "Asia/Hovd", "MN-057": "Asia/Hovd",
    "GL-SE": "America/Nuuk", "GL-KU": "America/Nuuk", "GL-QA": "America/Nuuk", "GL-AV": "America/Nuuk",
}  # fmt: skip

# Airports that break their state's rule (the split states).
AIRPORT = {
    "ELP": "America/Denver",  # El Paso, Texas: Mountain
    "PNS": "America/Chicago",  # Pensacola, Florida panhandle: Central
    "VPS": "America/Chicago",
    "ECP": "America/Chicago",
    "TLH": "America/New_York",
    "EVV": "America/Chicago",  # Evansville, Indiana: Central
    "SDF": "America/Kentucky/Louisville",
    "LEX": "America/New_York",
    "PAH": "America/Chicago",
    "TYS": "America/New_York",
    "TRI": "America/New_York",
    "CHA": "America/New_York",  # East Tennessee
    "BOI": "America/Boise",
    "IDA": "America/Boise",
    "LWS": "America/Los_Angeles",
    "RAP": "America/Denver",
    "BIS": "America/Chicago",
    "MOT": "America/Chicago",  # Rapid City: Mountain
    "OME": "America/Nome",
    "ADK": "America/Adak",
    "CUN": "America/Cancun",
    "CZM": "America/Cancun",
    "CJS": "America/Ciudad_Juarez",
    "PVR": "America/Mexico_City",  # Puerto Vallarta is in Jalisco: Central
}


def zone_of(iata: str, country: str, region: str) -> str | None:
    return AIRPORT.get(iata) or REGION.get(region) or COUNTRY.get(country)


def main(argv: list[str]) -> int:
    if argv:
        text = Path(argv[0]).read_text(encoding="utf-8")
    else:
        with urllib.request.urlopen(URL, timeout=60) as response:
            text = response.read().decode("utf-8")
    rows = []
    missing = []
    for r in csv.DictReader(io.StringIO(text)):
        if r["type"] != "large_airport" or r["scheduled_service"] != "yes":
            continue
        iata, icao = r["iata_code"].strip().upper(), r["icao_code"].strip().upper()
        if len(iata) != 3 or len(icao) != 4 or not iata.isalpha() or not icao.isalnum():
            continue
        zone = zone_of(iata, r["iso_country"], r["iso_region"])
        if zone is None:
            missing.append(f"{iata} {r['iso_region']} {r['name']}")
            continue
        zoneinfo.ZoneInfo(zone)  # raises on a name the zone database does not know
        lat, lon = round(float(r["latitude_deg"]), 4), round(float(r["longitude_deg"]), 4)
        rows.append((iata, icao, r["name"], lat, lon, zone))
    rows.sort()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as fh:
        fh.write(HEADER)
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(("iata", "icao", "name", "lat", "lon", "tz"))
        writer.writerows(rows)
    for m in missing:
        print(f"no zone: {m}", file=sys.stderr)
    print(f"wrote {len(rows)} airports to {OUT}; {len(missing)} without a zone")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
