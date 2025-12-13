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
from openpyxl.styles import Border, Side
import requests  # <--- NEW IMPORT FOR SPEED

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
    
    # SPEED FIX: Don't wait for full page load (images, ads), just HTML
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
    """
    Uses 'requests' instead of Selenium. 
    This is 20x faster because it doesn't launch a browser.
    """
    website_data_lower = {}
    try:
        # Fake a browser user-agent to avoid getting blocked
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        response = requests.get(URL, headers=headers, timeout=10)
        
        # If response is successful, parse the HTML
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
        
        # Hardcoded to 5 browsers for speed
        workers = 5
        
        if st.button("Search for prices", type="primary"):
            st.toast("🚀 Scraper started! Please wait...", icon="🤖")
            status = st.empty()
            status.info("⏳ Initializing browsers... (Takes ~5-10s)")
            bar = st.progress(0)

            tasks = []
            
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
                # Process data
                df = pd.DataFrame(all_data).drop_duplicates(subset=['Match', 'Provider'])
                df['Date'] = pd.to_datetime(df['Date'])
                df_pivot = df.pivot(index='Match', columns='Provider', values=['Price', 'Nights'])
                final_df = pd.DataFrame(index=df_pivot.index)
                
                # Map Club names
                match_to_club = df.set_index('Match')['Club'].to_dict()
                final_df.insert(0, 'Club', final_df.index.map(match_to_club))
                
                for prov in sorted(df['Provider'].unique()):
                    if prov in df_pivot['Price']: final_df[prov] = df_pivot['Price'][prov]
                    if prov in df_pivot['Nights']: final_df[f"{prov} nætter"] = df_pivot['Nights'][prov]

                final_df = final_df.sort_values(by=['Club'])

                # Excel Formatting
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    final_df.to_excel(writer, sheet_name='Prices')
                    workbook = writer.book
                    worksheet = writer.sheets['Prices']
                    thick_border = Border(top=Side(style='thick'))
                    previous_club = final_df.iloc[0]['Club']
                    
                    for i, row in enumerate(final_df.itertuples(), start=2):
                        current_club = row.Club
                        if current_club != previous_club:
                            for cell in worksheet[i]:
                                cell.border = thick_border
                            previous_club = current_club

                # Safe filename (Using _ instead of :)
                timestamp = datetime.now().strftime("%m-%d_%H-%M")
                file_name = f"prices_{timestamp}.xlsx"
                
                st.download_button(
                    label="📥 Download Excel Report",
                    data=output.getvalue(),
                    file_name=file_name,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
                
                st.dataframe(final_df)
            else:
                st.warning("No data found.")

if __name__ == "__main__":
    main()
