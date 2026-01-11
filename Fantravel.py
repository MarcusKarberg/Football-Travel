import time
import re
import requests
import pandas as pd
import concurrent.futures # Nødvendig til threading
from datetime import datetime
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# --- CONFIGURATION ---
URL = "https://fantravel.dk/"
PROVIDER_NAME = "Fantravel.dk"
CURRENT_YEAR = 2026
MAX_WORKERS = 4

# --- ALIAS IMPORT ---
try:
    from Alias import club_alias
except ImportError:
    club_alias = {}

# --- HELPER FUNCTIONS ---

def get_driver():
    """Starts Chrome driver."""
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-notifications")
    # For at spare ressourcer i tråde:
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-extensions")
    return webdriver.Chrome(options=chrome_options)

def clean_price(price_str):
    if isinstance(price_str, (int, float)): return float(price_str)
    try:
        clean = str(price_str).lower().replace('dkk', '').replace('kr.', '').replace('.', '').replace(',', '.')
        return float(clean.strip())
    except: return 0.0

def parse_danish_date(date_str, default_year=CURRENT_YEAR):
    dk_months = {
        "januar": 1, "februar": 2, "marts": 3, "april": 4, "maj": 5, "juni": 6,
        "juli": 7, "august": 8, "september": 9, "oktober": 10, "november": 11, "december": 12
    }
    try:
        match = re.search(r"(\d+)\.?\s+([a-zA-Z]+)", date_str)
        if match:
            day = int(match.group(1))
            month_name = match.group(2).lower()
            month = dk_months.get(month_name, 1)
            
            year_match = re.search(r"20\d{2}", date_str)
            year = int(year_match.group(0)) if year_match else default_year
            
            return datetime(year, month, day)
    except: pass
    return pd.NaT

def calculate_nights(text_string, year=CURRENT_YEAR):
    try:
        match = re.search(r"fra\s+(.*?)\s+til\s+(.*?)($|<)", text_string, re.IGNORECASE)
        if not match: return 0

        d1 = parse_danish_date(match.group(1).strip(), year)
        d2 = parse_danish_date(match.group(2).strip(), year)

        if pd.isna(d1) or pd.isna(d2): return 0

        if d2 < d1:
            d2 = d2.replace(year=d1.year + 1)

        delta = d2 - d1
        return delta.days
    except: return 0

def check_club_match(row_text, selected_clubs):
    row_text_lower = str(row_text).lower()
    for club in selected_clubs:
        if club.lower() in row_text_lower:
            return club
        if club in club_alias:
            for alias in club_alias[club]:
                if alias.lower() in row_text_lower:
                    return club 
    return None

def handle_cookies(driver):
    try:
        xpath = "//*[contains(translate(text(), 'KUN NØDVENDIGE', 'kun nødvendige'), 'kun nødvendige') or contains(text(), 'Afvis')]"
        btn = WebDriverWait(driver, 3).until(EC.element_to_be_clickable((By.XPATH, xpath)))
        btn.click()
        time.sleep(1)
    except: pass

# --- WORKER FUNCTION ---

def process_match_batch(match_data_list):
    """
    Denne funktion køres af hver tråd.
    Den får en liste af kampe, åbner én browser, og behandler dem.
    """
    if not match_data_list:
        return []

    batch_results = []
    driver = get_driver()
    
    try:
        # Håndter cookies én gang per tråd hvis muligt, ellers per side
        first_run = True

        for item in match_data_list:
            url = item['url']
            club_name = item['club']
            
            try:
                driver.get(url)
                if first_run:
                    handle_cookies(driver)
                    first_run = False
                
                # Vent lidt på load - mere robust end fast sleep
                try:
                    WebDriverWait(driver, 5).until(
                        EC.presence_of_element_located((By.CLASS_NAME, "booking-title"))
                    )
                except:
                    time.sleep(1) # Fallback

                # A. Match Name
                try:
                    title_elem = driver.find_element(By.CLASS_NAME, "booking-title")
                    raw_title = title_elem.text
                    match_name = raw_title.replace("Book din fodboldrejse til", "").strip()
                except:
                    match_name = f"{club_name} Match"

                # B. Price (Ticket + Hotel)
                price = 0.0
                try:
                    price_elem = driver.find_element(By.CSS_SELECTOR, ".package-option.package-hotel .woocommerce-Price-amount bdi")
                    price = clean_price(price_elem.text)
                except:
                    continue # Skip hvis ingen pris

                # C. Dates & Nights
                sort_date = pd.NaT
                nights = 0
                try:
                    xpath_date = "//div[contains(@class, 'package-hotel')]//li[contains(text(), 'Hotelophold fra')]"
                    date_elem = driver.find_element(By.XPATH, xpath_date)
                    date_text = date_elem.text
                    
                    nights = calculate_nights(date_text, CURRENT_YEAR)
                    
                    match_start_date = re.search(r"fra\s+(.*?)\s+til", date_text)
                    if match_start_date:
                        sort_date = parse_danish_date(match_start_date.group(1), CURRENT_YEAR)
                except:
                    pass
                
                if pd.isna(sort_date):
                    sort_date = datetime(2100, 1, 1)

                batch_results.append({
                    "Club": club_name,
                    "Match": match_name,
                    "SortDate": sort_date,
                    "Price": price,
                    "Provider": PROVIDER_NAME,
                    "Nights": int(nights) if isinstance(nights, int) else 0
                })
            except Exception as e:
                # print(f"Fejl på link {url}: {e}") # Debugging
                continue

    finally:
        driver.quit()
        
    return batch_results

# --- MAIN EXPORT FUNCTION ---

def get_prices(selected_clubs):
    """
    Main function called by Streamlit.
    """
    print(f"--- FANTRAVEL: Starter søgning for {selected_clubs} ---")
    
    # 1. Fast Scan (Requests) to find club links
    club_links_map = {}
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(URL, headers=headers, timeout=10)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.content, "html.parser")
            dropdown = soup.find("div", class_="fantravel-leagues-dropdown")
            if dropdown:
                for link in dropdown.find_all("a"):
                    link_text = link.get_text(strip=True)
                    matched_club = check_club_match(link_text, selected_clubs)
                    if matched_club:
                        club_links_map[matched_club] = link.get("href")
    except Exception as e:
        print(f"Fantravel Error (Init): {e}")
        return pd.DataFrame()

    if not club_links_map:
        return pd.DataFrame()

    # 2. Collect Match URLs (Single Driver - Fast)
    # Vi henter kun links her, vi besøger dem ikke.
    matches_to_scrape = [] 
    
    driver = get_driver()
    try:
        for club_name, club_url in club_links_map.items():
            try:
                driver.get(club_url)
                time.sleep(1)
                handle_cookies(driver)

                # Click "Vis kun hjemmekampe"
                driver.execute_script("window.scrollBy(0, 200);")
                time.sleep(0.5)
                try:
                    xpath = "//a[contains(@class, 'drag_scroll_item') and contains(@href, 'vis-kun-hjemmekampe')]"
                    btn = WebDriverWait(driver, 4).until(EC.element_to_be_clickable((By.XPATH, xpath)))
                    btn.click()
                    time.sleep(2)
                except: pass

                # Get match links
                soup = BeautifulSoup(driver.page_source, "html.parser")
                match_links = [l.get("href") for l in soup.find_all("a", class_="product_table_single") if l.get("href")]
                
                for link in match_links:
                    matches_to_scrape.append({
                        "club": club_name,
                        "url": link
                    })
                    
            except Exception as e:
                print(f"Fantravel Error ({club_name}): {e}")
    finally:
        driver.quit()

    print(f"--- FANTRAVEL: Fandt {len(matches_to_scrape)} kampe. Starter tråde... ---")

    # 3. Parallel Processing (Worker Threads)
    final_data = []
    
    if matches_to_scrape:
        # Del listen op i chunks baseret på MAX_WORKERS
        # Dette sikrer, at hver tråd får en stak links og beholder sin browser åben
        chunk_size = (len(matches_to_scrape) + MAX_WORKERS - 1) // MAX_WORKERS
        chunks = [matches_to_scrape[i:i + chunk_size] for i in range(0, len(matches_to_scrape), chunk_size)]
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            # Map hver chunk til worker-funktionen
            results = list(executor.map(process_match_batch, chunks))
            
            # Saml resultaterne (results er en liste af lister)
            for batch in results:
                final_data.extend(batch)

    # Return DataFrame
    return pd.DataFrame(final_data)