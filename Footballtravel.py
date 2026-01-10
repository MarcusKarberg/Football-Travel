import pandas as pd
import requests
import io
import re
from datetime import datetime

# --- IMPORT ALIAS ---
try:
    from Alias import club_alias
except ImportError:
    club_alias = {}

# --- KONFIGURATION ---
CSV_URL = "https://api.footballtravel.com/feed/footballtravel-dk/all-offers.csv"
PROVIDER_NAME = "FootballTravel.dk"

def load_csv_data():
    try:
        response = requests.get(CSV_URL, timeout=10)
        response.raise_for_status()
        df = pd.read_csv(io.StringIO(response.text), sep=',', header=None, on_bad_lines='skip')
        return df
    except Exception as e:
        print(f"Fejl ved CSV hentning: {e}")
        return pd.DataFrame()

def clean_price(price_str):
    if isinstance(price_str, (int, float)): return float(price_str)
    try:
        clean = str(price_str).lower().replace('dkk', '').replace('kr.', '').replace('.', '').replace(',', '.')
        return float(clean.strip())
    except: return 0.0

def clean_nights(nights_str):
    try:
        match = re.search(r'(\d+)', str(nights_str))
        if match: return int(match.group(1))
        return 0
    except: return 0

def check_club_match(row_text, selected_clubs):
    """
    Tjekker om en af de valgte klubber (eller deres aliaser) findes i teksten.
    """
    row_text_lower = str(row_text).lower()
    
    for club in selected_clubs:
        # 1. Tjek det direkte navn
        if club.lower() in row_text_lower:
            return club
        
        # 2. Tjek aliaser
        if club in club_alias:
            for alias in club_alias[club]:
                if alias.lower() in row_text_lower:
                    return club 
    return None

def get_prices(selected_clubs):
    full_df = load_csv_data()
    if full_df.empty: return pd.DataFrame()

    processed_data = []
    
    # Kolonne indexer
    IDX_FILTER_TYPE = 1   # B
    IDX_PRICE = 4         # E
    IDX_FILTER_CLUB = 7   # H
    IDX_OPPONENT = 8      # I
    IDX_DATE = 14         # O
    IDX_NIGHTS = 16       # Q

    for index, row in full_df.iterrows():
        if len(row) <= IDX_NIGHTS: continue
        try:
            # 1. TJEK KLUB
            row_club_text = str(row[IDX_FILTER_CLUB]).strip()
            found_club = check_club_match(row_club_text, selected_clubs)
            if not found_club: continue

            # 2. TJEK TYPE
            if "billet + hotel" not in str(row[IDX_FILTER_TYPE]).lower(): continue

            # 3. PRIS
            price = clean_price(row[IDX_PRICE])
            if price < 10: continue

            # 4. DATA
            nights = clean_nights(row[IDX_NIGHTS])
            
            date_obj = pd.NaT
            try:
                # HER VAR FEJLEN: Vi tilføjer dayfirst=True
                # Dette tvinger pandas til at læse 07/02 som 7. feb, ikke 2. juli
                date_obj = pd.to_datetime(str(row[IDX_DATE]), dayfirst=True, errors='coerce')
            except: pass
            
            sort_date = date_obj if pd.notnull(date_obj) else datetime(2100, 1, 1)

            # 5. NAVN
            match_name = f"{str(row[IDX_FILTER_CLUB]).strip()} – {str(row[IDX_OPPONENT]).strip()}"

            processed_data.append({
                "Club": found_club,
                "Match": match_name,
                "SortDate": sort_date,
                "Price": price,
                "Provider": PROVIDER_NAME,
                "Nights": nights
            })
        except: continue
        
    return pd.DataFrame(processed_data)