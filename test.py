import pandas as pd
import io
import requests
import re
import time
import random  # Import random to vary sleep times
from datetime import datetime
from playwright.sync_api import sync_playwright

# --- CONFIGURATION ---
URL_TEMPLATE = "https://olka.dk/event/soccer/{date}-{home}-{away}/"

# Mapping for URL slugs
TEAM_MAPPING = {
    "Bournemouth": "bournemouth",
    "Aston Villa": "aston-villa",
    "Leeds": "leeds-united",
    "Brentford": "brentford",
    "Burnley": "burnley",
    "Brighton": "brighton",
    "Chelsea": "chelsea-fc",
    "Crystal Palace": "crystal-palace",
    "Everton": "everton",
    "Fulham": "fulham-fc",
    "Liverpool FC": "liverpool-fc",
    "Manchester United": "manchester-united",
    "Newcastle": "newcastle-united",
    "Nottingham Forest": "nottingham-forest",
    "Sunderland": "sunderland",
    "West Ham": "west-ham",
    "Wolverhampton": "wolves",
    "Tottemnham": "tottenham",
    "FC Kairat": "kairat-almaty",
    "Qarabag FK": "qarabag",
}

def get_slug(team_name, is_home=False):
    """Generates the URL slug for a team."""
    if not isinstance(team_name, str): return ""
    clean_name = team_name.strip()
    
    if "Arsenal" in clean_name:
        return "arsenal-" if is_home else "arsenal-fc"
            
    for key, slug in TEAM_MAPPING.items():
        if key.lower() in clean_name.lower():
            return slug

    generel_slug = clean_name.lower()
    generel_slug = re.sub(r'\s+', '-', generel_slug)
    return generel_slug

def generate_links(selected_clubs):
    """Fetches CSV data and generates a DataFrame of matches with Links."""
    url = "https://api.footballtravel.com/feed/footballtravel-dk/all-offers.csv"
    print("Fetching CSV data...")
    
    try:
        response = requests.get(url)
        response.encoding = 'utf-8'
        df = pd.read_csv(io.StringIO(response.text))
        
        col_b_values = df.iloc[:, 1].astype(str).str.strip().str.lower()
        df_filtered = df[col_b_values == 'billet + hotel'].copy()
        
        mask = df_filtered.iloc[:, 7].astype(str).apply(lambda x: any(club.lower() in x.lower() for club in selected_clubs))
        results = df_filtered[mask].iloc[:, [7, 8, 14]].copy()
        results.columns = ['Home', 'Away', 'Date']
        results = results.drop_duplicates()
        
    except Exception as e:
        print(f"Error fetching CSV: {e}")
        return pd.DataFrame()

    generated_links = []
    print(f"Found {len(results)} matches. Generating links...")

    for index, row in results.iterrows():
        try:
            date_obj = pd.to_datetime(row['Date'], dayfirst=True)
            date_str = date_obj.strftime("%Y-%m-%d")
            display_date = date_obj.strftime("%d/%m/%Y")
            
            home_team = row['Home'].strip()
            away_team = row['Away'].strip()
            
            home_slug = get_slug(home_team, is_home=True)
            away_slug = get_slug(away_team, is_home=False)
            
            link = URL_TEMPLATE.format(date=date_str, home=home_slug, away=away_slug)
            match_display = f"{home_team} – {away_team}"

            generated_links.append({
                'Sort_Club': home_team,
                'Sort_Date': date_obj,
                'Date': display_date,
                'Match': match_display,
                'Link': link
            })
            
        except Exception as e:
            print(f"Error processing row {row}: {e}")

    if not generated_links:
        return pd.DataFrame()

    df_final = pd.DataFrame(generated_links)
    df_final = df_final.sort_values(by=['Sort_Club', 'Sort_Date'])
    return df_final

def scrape_prices(df_matches):
    """Iterates through the DataFrame and scrapes prices with human-like delays."""
    print("\nStarting Scraper (Browser will open)...")
    
    prices = []
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True) 
        page = browser.new_page()
        
        total = len(df_matches)
        
        for index, row in df_matches.iterrows():
            url = row['Link']
            print(f"[{index + 1}/{total}] Checking: {row['Match']}")
            
            # --- HUMAN DELAY START ---
            # Sleep randomly between 2.5 and 5.5 seconds before loading the next page
            sleep_time = random.uniform(2.5, 5.5)
            print(f"   ...waiting {sleep_time:.2f}s to act human...")
            time.sleep(sleep_time) 
            # -------------------------

            try:
                page.goto(url, timeout=60000)

                # Small delay after load to let JS settle
                time.sleep(random.uniform(1.0, 2.0))

                try:
                    cookie_knap = page.get_by_role("button", name=re.compile("Godkend|Allow all|Accepter", re.IGNORECASE))
                    if cookie_knap.is_visible(timeout=2000):
                        cookie_knap.click()
                        time.sleep(0.5) # Short pause after clicking
                except:
                    pass

                pakke_kort = page.locator("div.package").filter(has_text="Billet + hotel").first
                
                if pakke_kort.count() > 0:
                    rå_tekst = pakke_kort.inner_text().replace('\xa0', ' ')
                    match = re.search(r'(\d[\d\s\.]*)\s?DKK', rå_tekst, re.IGNORECASE)
                    
                    if match:
                        pris_str = match.group(1)
                        ren_pris = re.sub(r'[^\d]', '', pris_str)
                        print(f"   -> Found Price: {ren_pris}")
                        prices.append(int(ren_pris))
                    else:
                        print("   -> Price format not found.")
                        prices.append(None)
                else:
                    print("   -> 'Billet + hotel' package not found.")
                    prices.append(None)

            except Exception as e:
                print(f"   -> Error: {e}")
                prices.append(None)
                
        browser.close()

    df_matches['Price'] = prices
    return df_matches

def main():
    my_clubs = [
        "Liverpool", 
    ]
    
    df = generate_links(my_clubs)
    
    if df.empty:
        print("No matches found.")
        return

    df_results = scrape_prices(df)
    
    output_df = df_results[['Date', 'Match', 'Price', 'Link']]
    
    print("\n" + "="*80)
    print("FINAL RESULTS")
    print("="*80)
    pd.set_option('display.max_colwidth', None)
    
    print(output_df.to_string(index=False))

if __name__ == "__main__":
    main()