"""Chart colour palette — kept consistent with legacy/vol_app.py."""

PALETTE: dict[str, str] = {
    "price":   "#1565C0",
    "ret1":    "#2E7D32",
    "vol20":   "#7B1FA2",
    "ret20":   "#00838F",
    "fret20":  "#E65100",
    "zvol20":  "#7B1FA2",
    "zret20":  "#00838F",
    "zfret20": "#E65100",
    "strat":   "#D84315",
    "bh":      "#546E7A",
    "down":    "#C62828",
    "grid":    "#424242",
    "orange":  "#FF6F00",
}

QUANTILE_COLOURS = ["#1565C0", "#5C9BD6", "#90A4AE", "#EF9A9A", "#C62828"]


SECTOR_COLOURS: dict[str, str] = {
    "Broad Market / Index":      "#1565C0",
    "Technology":                "#7B1FA2",
    "Financials":                "#1B5E20",
    "Healthcare":                "#BF360C",
    "Consumer Discretionary":    "#E65100",
    "Consumer Staples":          "#F9A825",
    "Energy":                    "#4E342E",
    "Industrials":               "#00695C",
    "Materials":                 "#37474F",
    "Real Estate":               "#880E4F",
    "Utilities":                 "#0D47A1",
    "Communication Services":    "#6A1B9A",
    "Commodities / Futures":     "#558B2F",
    "Fixed Income / Bonds":      "#00838F",
    "Crypto":                    "#FF6F00",
    "Unclassified":              "#9E9E9E",
}


def sector_colour(sector: str | None) -> str:
    return SECTOR_COLOURS.get(sector or "Unclassified", SECTOR_COLOURS["Unclassified"])
