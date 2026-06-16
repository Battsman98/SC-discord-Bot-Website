from urllib.parse import parse_qs, unquote, urlparse
import json

from src.sources.sc_trade_tools import build_trade_route_url


def test_build_trade_route_url_encodes_query() -> None:
    url = build_trade_route_url("Ironclad Assault", 1_000_000, 5)
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    payload = json.loads(unquote(query["q"][0]))

    assert parsed.scheme == "https"
    assert parsed.netloc == "sc-trade.tools"
    assert payload == {
        "ship": "Ironclad Assault",
        "investment": 1_000_000,
        "maxStops": 5,
    }
