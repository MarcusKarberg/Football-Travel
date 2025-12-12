import os
import sys
import time
import re
import unicodedata
from urllib.parse import urljoin
import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
import concurrent.futures
import streamlit as st

# --- Setup Paths & Imports ---
# We use try/except to handle running this both as a script and via Streamlit
try:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(current_dir)
    sys.path.append(parent_dir)
    from Alias import club_alias, suffix_pattern
except ImportError:
    # Fallback if Alias is not found (for testing without the full environment)
    st.warning("Could not import 'Alias'. Ensure Alias.py is in the parent directory.")
    club_alias = {}
    suffix_pattern = re.compile(r"")

# --- Constants ---
URL = "https://www.fodboldrejseguiden.dk/fodboldrejser-england/"

# --- Page Config & Custom CSS for Green Buttons ---
st.set_page_config(page_title="Football Scraper", layout="wide")

st.markdown("""
<style>
    /* Force primary buttons (selected clubs) to be Green */
    div[data-testid="stButton"] > button[kind="primary"] {
        background-color: #28a745 !important;
        border-color: #28a745 !important; 
        color: white !important;
    }
    /* Style the scrape button differently to distinguish it */
    div.stButton > button.scrape-btn {
        background-color: #007bff;
        width: 100%;
    }
</style>
""", unsafe_allow_html=True)

# --- Helper Functions ---
def get_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new") 
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-notifications")
    chrome_options.add_argument("--log-level=3")
    return webdriver.Chrome(options=chrome_options)

def clean(text):
    if not isinstance(text, str): return ""
    text = unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('utf-8')
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

# --- Caching Data Loading ---
@st.cache_resource
def get_club_names():
    """Reads club names from Excel once."""
    try:
        excel_path = os.path.join(parent_dir, "club_names.xlsx")
        df_clubs = pd.read_excel(excel_path, sheet_name="EN", usecols="A", header=None)
        return df_clubs[0].dropna().astype(str).str.strip().tolist()
    except Exception as e:
        st.error(f"Error reading Excel file: {e}")
        return []

@st.cache_resource
def fetch_website_urls():
    """Scrapes the main page once to map Club Names -> URLs."""
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
    finally:
        setup_driver.quit()
    return website_data_lower

# --- Scraper Logic (Worker) ---
def scrape_specific_club(club_info):
    excel_name, club_url = club_info
    local_data = [] 
    
    driver = get_driver()
    
    try:
        driver.get(club_url)
        
        # Cookie Handling
        for _ in range(5):
            try:
                cookie_btn = driver.find_element(By.ID, 'onetrust-accept-btn-handler')
                driver.execute_script("arguments[0].click();", cookie_btn)
                time.sleep(1)
                break
            except:
                time.sleep(1)

        try:
            WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CLASS_NAME, "match")))
            scroll_slowly(driver)
            driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(2) 

            matches = driver.find_elements(By.CLASS_NAME, "match")
            
            for i, match in enumerate(matches):
                try:
                    if match.get_attribute("data-is-away") == "true": continue

                    match_date = match.get_attribute("data-date")
                    try:
                        title_elem = match.find_element(By.CLASS_NAME, "toggle_title")
                        match_title = title_elem.text.split("fra kr")[0].strip()
                    except:
                        match_title = f"Ukendt Kamp {i}"

                    driver.execute_script("arguments[0].scrollIntoView(true);", match)
                    driver.execute_script("window.scrollBy(0, -250);") 
                    time.sleep(0.3)
                    
                    toggle_btn = match.find_element(By.CSS_SELECTOR, ".togglemodule .koebsknap.toggle")
                    driver.execute_script("arguments[0].click();", toggle_btn)
                    time.sleep(1) 
                    
                    package_groups = match.find_elements(By.CSS_SELECTOR, ".packageholder .table-outer")
                    if not package_groups:
                        driver.execute_script("arguments[0].click();", toggle_btn)
                        time.sleep(1)
                        package_groups = match.find_elements(By.CSS_SELECTOR, ".packageholder .table-outer")
                    
                    if not package_groups: continue

                    for group in package_groups:
                        try:
                            header_elem = group.find_element(By.CSS_SELECTOR, "span.pack")
                            header = header_elem.get_attribute("innerText").strip().lower()
                            if "fly" not in header or "hotel" not in header: continue

                            rows = group.find_elements(By.CSS_SELECTOR, "tbody tr")
                            for row in rows:
                                try:
                                    provider = row.find_element(By.TAG_NAME, "td").text.strip()
                                    btn = row.find_element(By.CLASS_NAME, "koebsknap")
                                    link = btn.get_attribute("href")
                                    price_clean = re.sub(r"[^\d]", "", btn.text)
                                    try:
                                        nights_clean = re.search(r"(\d+)", row.find_element(By.CLASS_NAME, "nightsamount").text).group(1)
                                    except: nights_clean = "N/A"

                                    if link and "bestil-tilbud" not in link:
                                        local_data.append({
                                            "Club": excel_name,
                                            "Date": match_date,
                                            "Match": match_title,
                                            "Provider": provider,
                                            "Price": price_clean,
                                            "Nights": nights_clean
                                        })
                                except: continue
                        except: continue
                except Exception: continue
            
        except Exception as e:
            print(f"Error scraping {excel_name}: {e}")

    finally:
        driver.quit()
        
    return local_data

# --- Main Streamlit App ---
def main():
    st.title("⚽ Premier League Scraper Dashboard")
    st.write("Select clubs to scrape by clicking the buttons below. Green buttons are selected.")

    # 1. Initialize Data
    excel_clubs = get_club_names()
    
    if "selected_clubs" not in st.session_state:
        st.session_state.selected_clubs = set()

    # 2. Setup URLs (Spinner on first load)
    with st.spinner("Fetching club URLs..."):
        website_data_lower = fetch_website_urls()

    # 3. Create Button Grid
    st.subheader("Select Clubs")
    cols = st.columns(4) # 4 buttons per row
    
    for i, club in enumerate(excel_clubs):
        col = cols[i % 4]
        is_selected = club in st.session_state.selected_clubs
        
        # Determine button style (Primary = Green/Selected, Secondary = Gray/Unselected)
        btn_type = "primary" if is_selected else "secondary"
        
        if col.button(club, key=club, type=btn_type, use_container_width=True):
            # Toggle selection logic
            if is_selected:
                st.session_state.selected_clubs.remove(club)
            else:
                st.session_state.selected_clubs.add(club)
            st.rerun() # Refresh to update button color immediately

    # 4. Scraping Execution
    selected_list = list(st.session_state.selected_clubs)
    
    if not selected_list:
        st.info("Please select at least one club to start scraping.")
    else:
        st.divider()
        st.write(f"### Ready to scrape {len(selected_list)} clubs")
        
        MAX_WORKERS = st.slider("Concurrent Browsers (Max Workers)", 1, 8, 5)
        
        if st.button(f"🚀 Start Scraping ({len(selected_list)} Clubs)", type="secondary"):
            
            # Prepare tasks
            tasks = []
            status_text = st.empty()
            progress_bar = st.progress(0)
            status_text.write("🔍 Preparing URLs...")
            
            for excel_name in selected_list:
                clean_excel_name = clean(excel_name)
                found_url = website_data_lower.get(clean_excel_name)
                
                if not found_url and excel_name in club_alias:
                    for alias in club_alias[excel_name]:
                        if clean(alias) in website_data_lower:
                            found_url = website_data_lower[clean(alias)]
                            break 
                
                if found_url:
                    tasks.append((excel_name, found_url))
                else:
                    st.warning(f"⚠️ No URL found for: {excel_name}")

            # Run Threads
            all_scraped_data = []
            completed_count = 0
            total_tasks = len(tasks)
            
            status_text.write(f"⚡ Starting {MAX_WORKERS} browsers...")
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                # Submit all tasks
                future_to_club = {executor.submit(scrape_specific_club, task): task[0] for task in tasks}
                
                for future in concurrent.futures.as_completed(future_to_club):
                    club_name = future_to_club[future]
                    try:
                        data = future.result()
                        all_scraped_data.extend(data)
                        completed_count += 1
                        # Update progress
                        progress = completed_count / total_tasks
                        progress_bar.progress(progress)
                        status_text.write(f"✅ Finished: {club_name} ({len(data)} deals)")
                    except Exception as exc:
                        st.error(f"{club_name} generated an exception: {exc}")

            status_text.success("🎉 Scraping Complete!")
            
            # 5. Process and Download
            if all_scraped_data:
                df_raw = pd.DataFrame(all_scraped_data)
                df_raw = df_raw.drop_duplicates(subset=['Match', 'Provider'])
                df_raw['Date'] = pd.to_datetime(df_raw['Date'])
                df_raw['Club'] = pd.Categorical(df_raw['Club'], categories=excel_clubs, ordered=True)
                df_raw = df_raw.sort_values(by=['Club', 'Date'])
                
                # Pivot Logic
                sorted_matches = df_raw['Match'].unique()
                df_pivot = df_raw.pivot(index='Match', columns='Provider', values=['Price', 'Nights'])
                
                # Reindex if possible, else just use what we have
                # (Intersection of available matches vs sorted matches)
                valid_matches = [m for m in sorted_matches if m in df_pivot.index]
                df_pivot = df_pivot.reindex(valid_matches)

                final_df = pd.DataFrame(index=df_pivot.index)
                unique_providers = sorted(df_raw['Provider'].unique())

                for provider in unique_providers:
                    if provider in df_pivot['Price']: final_df[provider] = df_pivot['Price'][provider]
                    else: final_df[provider] = ""
                    
                    col_name_nights = f"{provider} nætter"
                    if provider in df_pivot['Nights']: final_df[col_name_nights] = df_pivot['Nights'][provider]
                    else: final_df[col_name_nights] = ""

                # Show Preview
                st.dataframe(final_df.head())

                # Download
                timestamp = datetime.now().strftime("%Y%m%d_%H%M")
                csv_data = final_df.to_csv().encode('utf-8-sig')
                
                st.download_button(
                    label="📥 Download CSV File",
                    data=csv_data,
                    file_name=f"EN_priser_{timestamp}.csv",
                    mime="text/csv",
                    type="primary"
                )
            else:
                st.warning("No data found for the selected clubs.")

if __name__ == "__main__":
    from datetime import datetime
    main()