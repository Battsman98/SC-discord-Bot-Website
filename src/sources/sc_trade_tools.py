import json
from urllib.parse import quote


SC_TRADE_TOOLS_ROUTE_URL = "https://sc-trade.tools/trade-routes"


def build_trade_route_url(
    ship: str,
    investment: int,
    max_stops: int = 5,
) -> str:
    query = {
        "ship": ship,
        "investment": investment,
        "maxStops": max_stops,
    }
    return f"{SC_TRADE_TOOLS_ROUTE_URL}?q={quote(json.dumps(query, separators=(',', ':')))}"
