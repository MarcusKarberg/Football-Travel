import re

club_alias = {
    # Premier League
    "Brighton": ["Brighton & Hove", "Brighton and Hove"],
    "Leeds": ["Leeds United"],
    "MANU": ["Manchester United"],
    "Newcastle": ["Newcastle United"],
    "Nottingham": ["Nottingham Forest"],
    "QPR": ["Queens Park Rangers"],
    "Tottenham": ["Spurs", "Tottenham Hotspur"],
    "West Ham": ["West Ham United"],
    "Wolverhampton": ["Wolves", "Wolverhampton Wanderers"],
    # Ligue 1
    "PSG": ["Paris Saint-Germain", "Paris St Germain", "Paris Saint Germain"],
    # La Liga
    "Celta": ["Celta Vigo", "Celta De Vigo"],
}

suffix_pattern = re.compile(
        r"\b(?:fc|FC|Fc|as|bk|rcd|ac|bc|ss|us|ogc|losc|afc|krc|sc|rb|cf|ik)\b\.?",
        re.IGNORECASE,
    )