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

# --- 1. SETUP CHROME DRIVER (Cloud Compatible) ---
def get_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new") 
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-notifications")
    
    # Check if running on Streamlit Cloud (Linux) to find Chromium
    if os.path.exists("/usr/bin/chromium"):
        chrome_options.binary_location = "/usr/bin/chromium"
    elif os.path.exists("/usr/bin/chromium-browser"):
        chrome_options.binary_location = "/usr/bin/chromium-browser"

    return webdriver.Chrome(options=chrome_options)

def clean(text):
    if not isinstance(text, str): return ""
    text = unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('utf-8')
    if suffix_pattern:
        text = suffix_pattern.sub("", text)
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

# --- 2. LOAD DATA (Assumes club_names.xlsx is in the same folder) ---
@st.cache_resource
def get_club_names():
    # We look for the file in the current working directory
    excel_filename = "club_names.xlsx"
    
    if not os.path.exists(excel_filename):
        st.error(f"❌ File not found: {excel_filename}")
        return []
        
    try:
        # Load the EN sheet
        df_clubs = pd.read_excel(excel_filename, sheet_name="EN", usecols="A", header=None)
        return df_clubs[0].dropna().astype(str).str.strip().tolist()
    except Exception as e:
        st.error(f"Error reading Excel: {e}")
        return []

@st.cache_resource
def fetch_website_urls():
    setup_driver = get_driver()
    website_data_lower = {}
    try:
        setup_driver.get(URL)
        try:
            WebDriverWait(setup_driver, 3).until(EC.element_to_be_clickable((By.ID, 'onetrust-accept-btn-handler'))).click()
        except: pass
        
        soup = BeautifulSoup(setup_driver.page_source, 'html.parser')
        section = soup.find(id="klubber")
        if section:
            for link in section.find_all('a'):
                clean_name = clean(link.get_text(strip=True))
                website_data_lower[clean_name] = urljoin(URL, link.get('href', ''))
    except Exception as e:
        st.error(f"Failed to fetch initial URLs: {e}")
    finally:
        setup_driver.quit()
    return website_data_lower

# --- 3. SCRAPER WORKER ---
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
                time.sleep(1)
                break
            except: time.sleep(1)

        try:
            WebDriverWait(driver, 8).until(EC.presence_of_element_located((By.CLASS_NAME, "match")))
            scroll_slowly(driver)
            driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(1.5) 

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
                    time.sleep(0.8) 
                    
                    package_groups = match.find_elements(By.CSS_SELECTOR, ".packageholder .table-outer")
                    if not package_groups:
                        driver.execute_script("arguments[0].click();", toggle_btn)
                        time.sleep(0.8)
                        package_groups = match.find_elements(By.CSS_SELECTOR, ".packageholder .table-outer")
                    
                    if not package_groups: continue

                    for group in package_groups:
                        try:
                            header = group.find_element(By.CSS_SELECTOR, "span.pack").get_attribute("innerText").strip().lower()
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

# --- 4. MAIN INTERFACE ---
def main():
    st.title("⚽ Prices: Ticket + Hotel")
    
    excel_clubs = get_club_names()
    if not excel_clubs:
        st.stop() 

    if "selected_clubs" not in st.session_state:
        st.session_state.selected_clubs = set()

    with st.spinner("Fetching URLs..."):
        website_data_lower = fetch_website_urls()

    st.subheader("Select Clubs")
    cols = st.columns(4)
    for i, club in enumerate(excel_clubs):
        col = cols[i % 4]
        is_sel = club in st.session_state.selected_clubs
        if col.button(club, key=club, type="primary" if is_sel else "secondary", use_container_width=True):
            if is_sel: st.session_state.selected_clubs.remove(club)
            else: st.session_state.selected_clubs.add(club)
            st.rerun()

    selected_list = list(st.session_state.selected_clubs)
    if selected_list:
        st.divider()
        st.write(f"### Ready to scrape {len(selected_list)} clubs")
        
        workers = 5
        
        if st.button("Search for prices", type="primary"):
            tasks = []
            status = st.empty()
            bar = st.progress(0)
            
            for name in selected_list:
                clean_name = clean(name)
                url = website_data_lower.get(clean_name)
                if not url and name in club_alias:
                    for a in club_alias[name]:
                        if clean(a) in website_data_lower:
                            url = website_data_lower[clean(a)]
                            break
                if url: tasks.append((name, url))
            
            all_data = []
            done = 0
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
                futures = {ex.submit(scrape_specific_club, t): t[0] for t in tasks}
                for f in concurrent.futures.as_completed(futures):
                    res = f.result()
                    all_data.extend(res)
                    done += 1
                    bar.progress(done / len(tasks))
                    status.write(f"✅ Processed {futures[f]} ({len(res)} deals)")
            
            if all_data:
                df = pd.DataFrame(all_data).drop_duplicates(subset=['Match', 'Provider'])
                df['Date'] = pd.to_datetime(df['Date'])
                
                # Pivot and organize columns
                df_pivot = df.pivot(index='Match', columns='Provider', values=['Price', 'Nights'])
                final_df = pd.DataFrame(index=df_pivot.index)
                
                for prov in sorted(df['Provider'].unique()):
                    if prov in df_pivot['Price']: final_df[prov] = df_pivot['Price'][prov]
                    if prov in df_pivot['Nights']: final_df[f"{prov} nætter"] = df_pivot['Nights'][prov]
                
                st.dataframe(final_df)
                st.download_button("📥 Download CSV", final_df.to_csv().encode('utf-8-sig'), "competitor_prices.csv", "text/csv")
            else:
                st.warning("No data found.")

if __name__ == "__main__":
    main()
