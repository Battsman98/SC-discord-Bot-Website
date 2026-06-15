from src.sources.star_citizen_wiki import StarCitizenWikiSource


def test_parse_result_uses_metadata() -> None:
    source = StarCitizenWikiSource.__new__(StarCitizenWikiSource)
    html = """
    <html>
      <head>
        <title>Carrack by Anvil Aerospace - Star Citizen</title>
        <meta name="description" content="The Anvil Carrack is an expedition ship.">
        <link rel="canonical" href="https://api.star-citizen.wiki/vehicles/anvl-carrack">
      </head>
      <body>Carrack</body>
    </html>
    """

    result = source._parse_result(html, "Carrack", "https://api.star-citizen.wiki/search/Carrack")

    assert result is not None
    assert result.title == "Carrack by Anvil Aerospace - Star Citizen"
    assert result.summary == "The Anvil Carrack is an expedition ship."
    assert result.url == "https://api.star-citizen.wiki/vehicles/anvl-carrack"


def test_parse_result_returns_none_for_no_results() -> None:
    source = StarCitizenWikiSource.__new__(StarCitizenWikiSource)

    result = source._parse_result("<html><body>No results found</body></html>", "nope", "https://example.com")

    assert result is None
