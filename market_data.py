# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Historical annual market data, used to drive the equity-return / inflation model.

Each entry is one calendar year paired together so the contemporaneous
relationship between nominal equity returns and CPI inflation is preserved when
the data is bootstrapped (sampling a year carries BOTH numbers).

Sources (fetched 2026-06):
- S&P 500 nominal total return (dividends reinvested): Damodaran / NYU Stern
  https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/histretSP.html
- CPI-U annual-average inflation: usinflationcalculator.com
  https://www.usinflationcalculator.com/inflation/historical-inflation-rates/

Values are percentages. Use the helpers below to get decimal fractions.
"""

from __future__ import annotations

# year -> (S&P 500 nominal total return %, CPI annual-average inflation %)
ANNUAL_PCT: dict[int, tuple[float, float]] = {
    1928: (43.81, -1.7), 1929: (-8.30, 0.0), 1930: (-25.12, -2.3),
    1931: (-43.84, -9.0), 1932: (-8.64, -9.9), 1933: (49.98, -5.1),
    1934: (-1.19, 3.1), 1935: (46.74, 2.2), 1936: (31.94, 1.5),
    1937: (-35.34, 3.6), 1938: (29.28, -2.1), 1939: (-1.10, -1.4),
    1940: (-10.67, 0.7), 1941: (-12.77, 5.0), 1942: (19.17, 10.9),
    1943: (25.06, 6.1), 1944: (19.03, 1.7), 1945: (35.82, 2.3),
    1946: (-8.43, 8.3), 1947: (5.20, 14.4), 1948: (5.70, 8.1),
    1949: (18.30, -1.2), 1950: (30.81, 1.3), 1951: (23.68, 7.9),
    1952: (18.15, 1.9), 1953: (-1.21, 0.8), 1954: (52.56, 0.7),
    1955: (32.60, -0.4), 1956: (7.44, 1.5), 1957: (-10.46, 3.3),
    1958: (43.72, 2.8), 1959: (12.06, 0.7), 1960: (0.34, 1.7),
    1961: (26.64, 1.0), 1962: (-8.81, 1.0), 1963: (22.61, 1.3),
    1964: (16.42, 1.3), 1965: (12.40, 1.6), 1966: (-9.97, 2.9),
    1967: (23.80, 3.1), 1968: (10.81, 4.2), 1969: (-8.24, 5.5),
    1970: (3.56, 5.7), 1971: (14.22, 4.4), 1972: (18.76, 3.2),
    1973: (-14.31, 6.2), 1974: (-25.90, 11.0), 1975: (37.00, 9.1),
    1976: (23.83, 5.8), 1977: (-6.98, 6.5), 1978: (6.51, 7.6),
    1979: (18.52, 11.3), 1980: (31.74, 13.5), 1981: (-4.70, 10.3),
    1982: (20.42, 6.2), 1983: (22.34, 3.2), 1984: (6.15, 4.3),
    1985: (31.24, 3.6), 1986: (18.49, 1.9), 1987: (5.81, 3.6),
    1988: (16.54, 4.1), 1989: (31.48, 4.8), 1990: (-3.06, 5.4),
    1991: (30.23, 4.2), 1992: (7.49, 3.0), 1993: (9.97, 3.0),
    1994: (1.33, 2.6), 1995: (37.20, 2.8), 1996: (22.68, 3.0),
    1997: (33.10, 2.3), 1998: (28.34, 1.6), 1999: (20.89, 2.2),
    2000: (-9.03, 3.4), 2001: (-11.85, 2.8), 2002: (-21.97, 1.6),
    2003: (28.36, 2.3), 2004: (10.74, 2.7), 2005: (4.83, 3.4),
    2006: (15.61, 3.2), 2007: (5.48, 2.8), 2008: (-36.55, 3.8),
    2009: (25.94, -0.4), 2010: (14.82, 1.6), 2011: (2.10, 3.2),
    2012: (15.89, 2.1), 2013: (32.15, 1.5), 2014: (13.52, 1.6),
    2015: (1.38, 0.1), 2016: (11.77, 1.3), 2017: (21.61, 2.1),
    2018: (-4.23, 2.4), 2019: (31.21, 1.8), 2020: (18.02, 1.2),
    2021: (28.47, 4.7), 2022: (-18.04, 8.0), 2023: (26.06, 4.1),
    2024: (24.88, 2.9), 2025: (17.78, 2.6),
}

YEARS: list[int] = sorted(ANNUAL_PCT)


def equity_returns() -> list[float]:
    """Nominal S&P 500 total returns as decimal fractions, in year order."""
    return [ANNUAL_PCT[y][0] / 100.0 for y in YEARS]


def inflation_rates() -> list[float]:
    """CPI annual-average inflation as decimal fractions, in year order."""
    return [ANNUAL_PCT[y][1] / 100.0 for y in YEARS]
