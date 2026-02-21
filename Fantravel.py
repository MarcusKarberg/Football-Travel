import time
import re
import requests
import pandas as pd
import concurrent.futures
import logging
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
MAX_WORKERS = 15 # Øget da requests-baserede tråde forbruger minimal RAM

# --- ALIAS IMPORT ---
try:
    from Alias import club_alias
except ImportError:
    club_alias = {}

# --- HELPER FUNCTIONS ---

def get_driver():
    chrome_options = Options()
    chrome_options.page_load_strategy = 'eager' # Blokerer indlæsning af subressourcer
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-notifications")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--blink-settings=imagesEnabled=false") # Forhindrer billed-download
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
            month = dk_months.get(match.group(2).lower(), 1)
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
        if d2 < d1: d2 = d2.replace(year=d1.year + 1)
        return (d2 - d1).days
    except: return 0

def check_club_match(row_text, selected_clubs):
    row_text_lower = str(row_text).lower()
    for club in selected_clubs:
        if club.lower() in row_text_lower: return club
        if club in club_alias:
            for alias in club_alias[club]:
                if alias.lower() in row_text_lower: return club 
    return None

# --- WORKER FUNCTION ---

def process_single_match(item):
    url = item['url']
    club_name = item['club']
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return None
            
        soup = BeautifulSoup(resp.content, "html.parser")

        # A. Match Name
        try:
            title_elem = soup.find(class_="booking-title")
            raw_title = title_elem.get_text(strip=True) if title_elem else ""
            match_name = raw_title.replace("Book din fodboldrejse til", "").strip() or f"{club_name} Match"
        except:
            match_name = f"{club_name} Match"

        # B. Price
        price = 0.0
        try:
            hotel_pkg = soup.find(class_="package-option package-hotel")
            if hotel_pkg:
                price_elem = hotel_pkg.find("bdi")
                if price_elem:
                    price = clean_price(price_elem.get_text(strip=True))
        except:
            return None

        if not price:
            return None

        # C. Dates & Nights
        sort_date = datetime(2100, 1, 1)
        nights = 0
        try:
            date_li = soup.find(lambda tag: tag.name == "li" and "Hotelophold fra" in tag.text)
            if date_li:
                date_text = date_li.get_text(strip=True)
                nights = calculate_nights(date_text, CURRENT_YEAR)
                match_start_date = re.search(r"fra\s+(.*?)\s+til", date_text)
                if match_start_date:
                    parsed_date = parse_danish_date(match_start_date.group(1), CURRENT_YEAR)
                    if not pd.isna(parsed_date):
                        sort_date = parsed_date
        except: pass

        return {
            "Club": club_name,
            "Match": match_name,
            "SortDate": sort_date,
            "Price": price,
            "Provider": PROVIDER_NAME,
            "Nights": int(nights) if isinstance(nights, int) else 0
        }
    except Exception as e:
        logging.error(f"Worker failed on {url}: {repr(e)}")
        return None

# --- MAIN EXPORT FUNCTION ---

def get_prices(selected_clubs):
    club_links_map = {}
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(URL, headers=headers, timeout=10)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.content, "html.parser")
            dropdowns = soup.find_all("div", class_="fantravel-leagues-dropdown")
            for dropdown in dropdowns:
                for link in dropdown.find_all("a"):
                    link_text = link.get_text(strip=True)
                    matched_club = check_club_match(link_text, selected_clubs)
                    if matched_club:
                        club_links_map[matched_club] = link.get("href")
    except Exception as e:
        logging.error(f"Fantravel Init Error: {repr(e)}")
        return pd.DataFrame()

    if not club_links_map:
        return pd.DataFrame()

    matches_to_scrape = [] 
    driver = get_driver()
    try:
        for club_name, club_url in club_links_map.items():
            try:
                driver.get(club_url)
                
                try:
                    xpath = "//*[contains(translate(text(), 'KUN NØDVENDIGE', 'kun nødvendige'), 'kun nødvendige') or contains(text(), 'Afvis')]"
                    WebDriverWait(driver, 3).until(EC.element_to_be_clickable((By.XPATH, xpath))).click()
                except: pass
                
                driver.execute_script("window.scrollBy(0, 200);")
                try:
                    xpath = "//a[contains(@class, 'drag_scroll_item') and contains(@href, 'vis-kun-hjemmekampe')]"
                    btn = WebDriverWait(driver, 4).until(EC.element_to_be_clickable((By.XPATH, xpath)))
                    btn.click()
                    time.sleep(1) # Påkrævet for DOM-rendering af nye links
                except: pass

                soup = BeautifulSoup(driver.page_source, "html.parser")
                match_links = [l.get("href") for l in soup.find_all("a", class_="product_table_single") if l.get("href")]
                
                for link in match_links:
                    matches_to_scrape.append({"club": club_name, "url": link})
                    
            except Exception as e:
                logging.error(f"Selenium UI loop failed for {club_name}: {repr(e)}")
    finally:
        driver.quit()

    final_data = []
    if matches_to_scrape:
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = [executor.submit(process_single_match, match) for match in matches_to_scrape]
            for future in concurrent.futures.as_completed(futures):
                try:
                    result = future.result()
                    if result:
                        final_data.append(result)
                except Exception as e:
                    logging.error(f"Thread execution crashed: {repr(e)}")

    return pd.DataFrame(final_data)