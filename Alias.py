import re

club_alias = {
    # Premier League
    "Brighton": ["Brighton & Hove", "Brighton and Hove"],
    "Leeds": ["Leeds United"],
    "Liverpool": ["Liverpool FC"],
    "Newcastle": ["Newcastle United"],
    "Nottingham": ["Nottingham Forest"],
    "QPR": ["Queens Park Rangers"],
    "Tottenham": ["Spurs", "Tottenham Hotspur"],
    "Wolverhampton": ["Wolves", "Wolverhampton Wanderers"],
    "West Ham": ["West Ham United"],
    # Ligue 1
    "PSG": ["Paris Saint-Germain", "Paris St Germain", "Paris Saint Germain"],
    # La Liga
    "Barcelona": ["FC Barcelona"],
    "Atletico Madrid": ["Atl√©tico Madrid", "Atlético Madrid", "Atlético"],
    "Celta": ["Celta Vigo", "Celta De Vigo"],
    # Serie A
    "AC Milan": ["Milan"]
}

suffix_pattern = re.compile(
        r"\b(?:fc|FC|Fc|as|bk|rcd|ac|bc|ss|us|ogc|losc|afc|krc|sc|rb|cf|ik)\b\.?",
        re.IGNORECASE,
    )

