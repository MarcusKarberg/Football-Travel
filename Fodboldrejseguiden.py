import time
import re
import unicodedata
from urllib.parse import urljoin
import pandas as pd
import requests
import concurrent.futures
import streamlit as st
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup

# --- IMPORT ALIAS ---
try:
    from Alias import club_alias, suffix_pattern
except ImportError:
    club_alias = {}
    suffix_pattern = None

URL = "https://www.fodboldrejseguiden.dk/fodboldrejser-england/"
PROVIDER_NAME = "Fodboldrejseguiden.dk"

# --- 1. SETUP CHROME DRIVER ---
def get_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new") 
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-notifications")
    chrome_options.page_load_strategy = 'eager' 
    
    import os
    if os.path.exists("/usr/bin/chromium"):
        chrome_options.binary_location = "/usr/bin/chromium"
    elif os.path.exists("/usr/bin/chromium-browser"):
        chrome_options.binary_location = "/usr/bin/chromium-browser"

    return webdriver.Chrome(options=chrome_options)

def clean(text):
    if not isinstance(text, str): return ""
    text = unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('utf-8')
    try:
        if suffix_pattern:
            text = suffix_pattern.sub("", text)
    except: pass
    return text.lower().strip()

def scroll_slowly(driver):
    last_height = driver.execute_script("return document.body.scrollHeight")
    retries = 0
    while True:
        current_scroll = driver.execute_script("return window.pageYOffset")
        while current_scroll < last_height:
            current_scroll += 500
            driver.execute_script(f"window.scrollTo(0, {current_scroll});")
            time.sleep(0.1)
        time.sleep(1.0)
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            if retries < 2:
                retries += 1
                time.sleep(1.0)
                continue
            else:
                break
        else:
            last_height = new_height
            retries = 0

# --- 2. FETCH URLS ---
@st.cache_resource(ttl=3600)
def fetch_website_urls():
    website_data_lower = {}
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(URL, headers=headers, timeout=10)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            section = soup.find(id="klubber")
            if section:
                for link in section.find_all('a'):
                    clean_name = clean(link.get_text(strip=True))
                    website_data_lower[clean_name] = urljoin(URL, link.get('href', ''))
    except Exception as e:
        print(f"Fejl ved URL hentning: {e}")
    return website_data_lower

# --- 3. SCRAPER WORKER ---
def scrape_specific_club(args):
    club_name, club_url = args
    local_data = []
    
    driver = get_driver()
    try:
        driver.get(club_url)
        
        try:
            cookie_btn = WebDriverWait(driver, 3).until(
                EC.element_to_be_clickable((By.ID, 'onetrust-accept-btn-handler'))
            )
            cookie_btn.click()
        except: pass

        try:
            WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.CLASS_NAME, "match")))
            scroll_slowly(driver)
            driver.execute_script("window.scrollTo(0, 0);")
            
            matches = driver.find_elements(By.CLASS_NAME, "match")
            
            for match in matches:
                try:
                    if match.get_attribute("data-is-away") == "true": continue
                    
                    match_date_str = match.get_attribute("data-date")
                    try:
                        title_elem = match.find_element(By.CLASS_NAME, "toggle_title")
                        match_title = title_elem.text.split("fra kr")[0].strip()
                    except: match_title = "Unknown Match"

                    try:
                        toggle_btn = match.find_element(By.CSS_SELECTOR, ".togglemodule .koebsknap.toggle")
                        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", toggle_btn)
                        driver.execute_script("arguments[0].click();", toggle_btn)
                        time.sleep(0.5)
                    except: pass
                    
                    package_groups = match.find_elements(By.CSS_SELECTOR, ".packageholder .table-outer")
                    
                    for group in package_groups:
                        try:
                            header = group.find_element(By.CSS_SELECTOR, "span.pack").get_attribute("innerText").strip().lower()
                            
                            if "fly" in header or "hotel" not in header: continue
                            
                            rows = group.find_elements(By.CSS_SELECTOR, "tbody tr")
                            for row in rows:
                                try:
                                    provider_text = row.find_element(By.TAG_NAME, "td").text.strip()
                                    
                                    # --- VIGTIG ÆNDRING: FILTRERING AF UDBYDER ---
                                    # Her tjekker vi, om udbyderen er "Footballtravel" (eller lignende).
                                    # Hvis ja, så springer vi over, da vi har data fra CSV.
                                    # Vi bruger .lower() og fjerner mellemrum for at fange "Football Travel", "footballtravel" osv.
                                    prov_check = provider_text.lower().replace(" ", "")
                                    
                                    if "footballtravel" in prov_check:
                                        # Vi ignorerer denne række, da den er hentet via CSV
                                        continue 
                                    # ---------------------------------------------

                                    btn = row.find_element(By.CLASS_NAME, "koebsknap")
                                    link = btn.get_attribute("href")
                                    
                                    raw_price = btn.text
                                    price_clean = float(re.sub(r"[^\d]", "", raw_price))
                                    
                                    try: 
                                        nights_text = row.find_element(By.CLASS_NAME, "nightsamount").text
                                        nights = int(re.search(r"(\d+)", nights_text).group(1))
                                    except: nights = 0

                                    if link and "bestil-tilbud" not in link:
                                        local_data.append({
                                            "Club": club_name,
                                            "Match": match_title,
                                            "SortDate": match_date_str,
                                            "Price": price_clean,
                                            "Provider": provider_text,
                                            "Nights": nights
                                        })
                                except: continue
                        except: continue
                except: continue
        except Exception: pass
    finally:
        driver.quit()
    
    return local_data

# --- 4. MAIN EXPORT FUNCTION ---
def get_prices(selected_clubs):
    website_urls = fetch_website_urls()
    tasks = []
    
    for club in selected_clubs:
        c_clean = clean(club)
        found_url = website_urls.get(c_clean)
        
        if not found_url and club in club_alias:
            for alias in club_alias[club]:
                if clean(alias) in website_urls:
                    found_url = website_urls[clean(alias)]
                    break
        
        if found_url:
            tasks.append((club, found_url))
    
    if not tasks:
        return pd.DataFrame()

    all_results = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        future_to_club = {executor.submit(scrape_specific_club, t): t[0] for t in tasks}
        
        for future in concurrent.futures.as_completed(future_to_club):
            try:
                data = future.result()
                if data:
                    all_results.extend(data)
            except Exception: pass

    df = pd.DataFrame(all_results)
    
    if not df.empty:
        df['SortDate'] = pd.to_datetime(df['SortDate'], errors='coerce')
        df = df.dropna(subset=['Price', 'SortDate'])
        
        cols = ["Club", "Match", "SortDate", "Price", "Provider", "Nights"]
        existing_cols = [c for c in cols if c in df.columns]
        df = df[existing_cols]

    return df