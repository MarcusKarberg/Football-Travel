import os
import sys
import time
import re
import unicodedata
from urllib.parse import urljoin
import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
import concurrent.futures
import streamlit as st
from datetime import datetime
import io
from openpyxl.styles import Border, Side, PatternFill, Font
from openpyxl.utils import get_column_letter
import requests

# --- IMPORT ALIAS (Assumes Alias.py is in the same folder) ---
try:
    from Alias import club_alias, suffix_pattern
except ImportError:
    st.error("❌ Critical Error: 'Alias.py' was not found in the same folder as this script.")
    st.stop()

URL = "https://www.fodboldrejseguiden.dk/fodboldrejser-england/"

# --- STREAMLIT CONFIG ---
st.set_page_config(page_title="Football Scraper", layout="wide")
st.markdown("""
<style>
    div[data-testid="stButton"] > button[kind="primary"] {
        background-color: #28a745 !important;
        border-color: #28a745 !important; 
        color: white !important;
    }
</style>
""", unsafe_allow_html=True)

# --- 1. SETUP CHROME DRIVER (OPTIMIZED) ---
def get_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new") 
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-notifications")
    
    # SPEED FIX: Don't wait for full page load
    chrome_options.page_load_strategy = 'eager' 
    
    # Check if running on Streamlit Cloud (Linux) to find Chromium
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
    except NameError: pass
    return text.lower().strip()

def scroll_slowly(driver):
    last_height = driver.execute_script("return document.body.scrollHeight")
    while True:
        current_scroll = driver.execute_script("return window.pageYOffset")
        while current_scroll < last_height:
            current_scroll += 350 
            driver.execute_script(f"window.scrollTo(0, {current_scroll});")
            time.sleep(0.2)
        time.sleep(1.5)
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height: break
        last_height = new_height

# --- 2. LOAD DATA ---
@st.cache_resource
def get_club_names():
    excel_filename = "club_names.xlsx"
    if not os.path.exists(excel_filename):
        st.error(f"❌ File not found: {excel_filename}")
        return []
    try:
        df_clubs = pd.read_excel(excel_filename, sheet_name="EN", usecols="A", header=None)
        return df_clubs[0].dropna().astype(str).str.strip().tolist()
    except Exception as e:
        st.error(f"Error reading Excel: {e}")
        return []

# --- 3. FETCH URLS (FAST VERSION) ---
@st.cache_resource
def fetch_website_urls():
    website_data_lower = {}
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        response = requests.get(URL, headers=headers, timeout=10)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            section = soup.find(id="klubber")
            if section:
                for link in section.find_all('a'):
                    clean_name = clean(link.get_text(strip=True))
                    website_data_lower[clean_name] = urljoin(URL, link.get('href', ''))
        else:
            st.error(f"Failed to load website. Status code: {response.status_code}")
            
    except Exception as e:
        st.error(f"Failed to fetch initial URLs: {e}")
    
    return website_data_lower

# --- 4. SCRAPER WORKER ---
def scrape_specific_club(club_info):
    excel_name, club_url = club_info
    local_data = [] 
    driver = get_driver()
    try:
        driver.get(club_url)
        # Cookie Banner
        for _ in range(3):
            try:
                cookie_btn = driver.find_element(By.ID, 'onetrust-accept-btn-handler')
                driver.execute_script("arguments[0].click();", cookie_btn)
                time.sleep(0.8)
                break
            except: time.sleep(0.8)

        try:
            WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.CLASS_NAME, "match")))
            scroll_slowly(driver)
            driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(1) 

            matches = driver.find_elements(By.CLASS_NAME, "match")
            for i, match in enumerate(matches):
                try:
                    if match.get_attribute("data-is-away") == "true": continue
                    match_date = match.get_attribute("data-date")
                    try:
                        title_elem = match.find_element(By.CLASS_NAME, "toggle_title")
                        match_title = title_elem.text.split("fra kr")[0].strip()
                    except: match_title = f"Match {i}"

                    driver.execute_script("arguments[0].scrollIntoView(true);", match)
                    driver.execute_script("window.scrollBy(0, -250);") 
                    time.sleep(0.2)
                    
                    toggle_btn = match.find_element(By.CSS_SELECTOR, ".togglemodule .koebsknap.toggle")
                    driver.execute_script("arguments[0].click();", toggle_btn)
                    time.sleep(0.6) 
                    
                    package_groups = match.find_elements(By.CSS_SELECTOR, ".packageholder .table-outer")
                    if not package_groups:
                        driver.execute_script("arguments[0].click();", toggle_btn)
                        time.sleep(0.6)
                        package_groups = match.find_elements(By.CSS_SELECTOR, ".packageholder .table-outer")
                    
                    if not package_groups: continue

                    for group in package_groups:
                        try:
                            header = group.find_element(By.CSS_SELECTOR, "span.pack").get_attribute("innerText").strip().lower()
                            # ONLY TICKET + HOTEL LOGIC
                            if "fly" in header or "hotel" not in header: continue
                            
                            for row in group.find_elements(By.CSS_SELECTOR, "tbody tr"):
                                try:
                                    provider = row.find_element(By.TAG_NAME, "td").text.strip()
                                    btn = row.find_element(By.CLASS_NAME, "koebsknap")
                                    link = btn.get_attribute("href")
                                    price_clean = re.sub(r"[^\d]", "", btn.text)
                                    try: nights = re.search(r"(\d+)", row.find_element(By.CLASS_NAME, "nightsamount").text).group(1)
                                    except: nights = "N/A"

                                    if link and "bestil-tilbud" not in link:
                                        local_data.append({
                                            "Club": excel_name, "Date": match_date, "Match": match_title,
                                            "Provider": provider, "Price": price_clean, "Nights": nights
                                        })
                                except: continue
                        except: continue
                except: continue
        except Exception: pass
    finally:
        driver.quit()
    return local_data

# --- 5. MAIN INTERFACE ---
def main():
    st.title("⏱️ Speed Diagnostic")
    
    if st.button("Run Speed Test", type="primary"):
        st.write("### 🕵️‍♂️ diagnosing the 30-second delay...")
        
        # --- TEST 1: The Website Connection ---
        st.write("1️⃣ Testing connection to 'fodboldrejseguiden.dk'...")
        start_net = time.time()
        try:
            # We simulate the exact request from fetch_website_urls
            headers = {"User-Agent": "Mozilla/5.0"}
            r = requests.get("https://www.fodboldrejseguiden.dk/fodboldrejser-england/", headers=headers, timeout=35)
            elapsed_net = round(time.time() - start_net, 2)
            
            if elapsed_net > 5:
                st.error(f"❌ SLOW: Website took {elapsed_net} seconds to respond.")
            else:
                st.success(f"✅ FAST: Website responded in {elapsed_net} seconds.")
        except Exception as e:
            st.error(f"❌ FAILED: Website connection error: {e}")

        # --- TEST 2: The Browser Startup ---
        st.write("2️⃣ Testing Chrome Driver startup...")
        start_driver = time.time()
        try:
            # This is the exact line that launches the browser
            driver = get_driver()
            elapsed_driver = round(time.time() - start_driver, 2)
            driver.quit()
            
            if elapsed_driver > 5:
                st.error(f"❌ SLOW: Chrome Driver took {elapsed_driver} seconds to launch.")
                st.info("💡 Fix: This usually means Selenium is trying to download updates and timing out.")
            else:
                st.success(f"✅ FAST: Chrome Driver launched in {elapsed_driver} seconds.")
        except Exception as e:
            st.error(f"❌ FAILED: Driver error: {e}")