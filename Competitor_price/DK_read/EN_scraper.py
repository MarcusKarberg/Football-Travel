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
from datetime import datetime

# --- Setup ---
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)
from Alias import club_alias, suffix_pattern 

URL = "https://www.fodboldrejseguiden.dk/fodboldrejser-england/"
# Hent klubber
df_clubs = pd.read_excel(os.path.join(parent_dir, "club_names.xlsx"), sheet_name="EN", usecols="A", header=None)
excel_clubs = df_clubs[0].dropna().astype(str).str.strip().tolist()

# Konfiguration
MAX_WORKERS = 5  # Antal samtidige browsere. Hæv til 5 hvis du har en stærk PC.

def get_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new") 
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-notifications")
    chrome_options.add_argument("--log-level=3") # Minimerer konsol-støj fra Chrome
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

# ==========================================
# WORKER FUNCTION (Kører i hver sin tråd)
# ==========================================
def scrape_specific_club(club_info):
    excel_name, club_url = club_info
    local_data = [] 
    
    driver = get_driver()
    
    try:
        driver.get(club_url)
        
        # --- FIX 1: AGGRESSIV COOKIE HÅNDTERING ---
        # Vi prøver i op til 5 sekunder at finde og fjerne banneret
        for _ in range(5):
            try:
                cookie_btn = driver.find_element(By.ID, 'onetrust-accept-btn-handler')
                driver.execute_script("arguments[0].click();", cookie_btn)
                print(f"   🍪 {excel_name}: Cookie banner fjernet.")
                time.sleep(1)
                break
            except:
                time.sleep(1)
        # ------------------------------------------

        try:
            WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CLASS_NAME, "match")))
            
            scroll_slowly(driver)
            
            # Hop til toppen og vent lidt længere på at layoutet sætter sig
            driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(2) 

            matches = driver.find_elements(By.CLASS_NAME, "match")
            
            for i, match in enumerate(matches):
                try:
                    if match.get_attribute("data-is-away") == "true": continue

                    match_date = match.get_attribute("data-date")
                    
                    # Sikker titel-udtrækning
                    try:
                        title_elem = match.find_element(By.CLASS_NAME, "toggle_title")
                        match_title = title_elem.text.split("fra kr")[0].strip()
                    except:
                        match_title = f"Ukendt Kamp {i}"

                    # --- FIX 2: JUSTERET SCROLL LOGIK ---
                    # Scroll elementet til toppen (true) og ryk det så 250px ned
                    driver.execute_script("arguments[0].scrollIntoView(true);", match)
                    driver.execute_script("window.scrollBy(0, -250);") 
                    time.sleep(0.3)
                    
                    toggle_btn = match.find_element(By.CSS_SELECTOR, ".togglemodule .koebsknap.toggle")
                    
                    # --- FIX 3: KLIK & VALIDERING ---
                    # Klik på knappen
                    driver.execute_script("arguments[0].click();", toggle_btn)
                    time.sleep(1) # Vent på animation
                    
                    # Tjek om vi faktisk kan se tabellerne. Hvis ikke, prøv et "Rescue Click"
                    package_groups = match.find_elements(By.CSS_SELECTOR, ".packageholder .table-outer")
                    if not package_groups:
                        # Prøv at klikke igen (nogle gange lukker den første gang pga. dobbelt-klik)
                        driver.execute_script("arguments[0].click();", toggle_btn)
                        time.sleep(1)
                        package_groups = match.find_elements(By.CSS_SELECTOR, ".packageholder .table-outer")
                    
                    if not package_groups:
                        print(f"      ⚠️ {match_title}: Kunne ikke åbne priser (ingen tabeller fundet).")
                        continue

                    # SCRAPE DATA
                    for group in package_groups:
                        try:
                            # Tjek header tekst (ignorer case sensitivity)
                            header_elem = group.find_element(By.CSS_SELECTOR, "span.pack")
                            header = header_elem.get_attribute("innerText").strip().lower() # Mere robust end .text
                            
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
                except Exception as e_match:
                    # HER SER DU FEJLEN NU:
                    print(f"      ❌ FEJL ved kamp '{excel_name}' index {i}: {e_match}")
                    continue
            
            print(f"✅ Færdig: {excel_name} ({len(local_data)} tilbud fundet)")
            
        except Exception as e:
            print(f"⚠️ Generel fejl ved {excel_name}: {e}")

    finally:
        driver.quit()
        
    return local_data

# ==========================================
# MAIN EXECUTION
# ==========================================
if __name__ == "__main__":
    print("🚀 Starter Multi-Threaded Scraper...")
    
    # 1. Hent alle links først (Dette gøres én gang, hurtigt)
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

    # 2. Forbered opgaveliste (Hvilke URL'er skal besøges?)
    tasks = []
    print(f"🔍 Forbereder {len(excel_clubs)} klubber...")
    
    for excel_name in excel_clubs:
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
            print(f"⚠️ {excel_name}: Intet link fundet.")

    # 3. Start Multi-Threading
    all_scraped_data = []
    print(f"\n⚡ Starter {MAX_WORKERS} samtidige browsere for at behandle {len(tasks)} klubber...")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Send alle opgaver afsted og vent på resultater
        results = executor.map(scrape_specific_club, tasks)
        
        for res in results:
            all_scraped_data.extend(res)

    # ==========================================
    # DATABEHANDLING
    # ==========================================
    if all_scraped_data:
        print(f"\n💾 Genererer endelig fil med {len(all_scraped_data)} rækker...")
        df_raw = pd.DataFrame(all_scraped_data)
        df_raw = df_raw.drop_duplicates(subset=['Match', 'Provider'])
        df_raw['Date'] = pd.to_datetime(df_raw['Date'])
        df_raw['Club'] = pd.Categorical(df_raw['Club'], categories=excel_clubs, ordered=True)
        df_raw = df_raw.sort_values(by=['Club', 'Date'])
        
        sorted_matches = df_raw['Match'].unique()
        df_pivot = df_raw.pivot(index='Match', columns='Provider', values=['Price', 'Nights'])
        df_pivot = df_pivot.reindex(sorted_matches)

        final_df = pd.DataFrame(index=df_pivot.index)
        unique_providers = sorted(df_raw['Provider'].unique())

        for provider in unique_providers:
            if provider in df_pivot['Price']: final_df[provider] = df_pivot['Price'][provider]
            else: final_df[provider] = ""
            
            col_name_nights = f"{provider} nætter"
            if provider in df_pivot['Nights']: final_df[col_name_nights] = df_pivot['Nights'][provider]
            else: final_df[col_name_nights] = ""

        # ... (Din kode der bygger final_df er herover) ...

        # ==========================================
        # GEM FIL (DATA/DATO/FILNAVN)
        # ==========================================
        
        # 1. Hent dags dato som tekst (f.eks. "2023-10-27")
        today_str = datetime.now().strftime("%Y-%m-%d")

        # 2. Definer stien: Script-mappe -> data -> dato-mappe
        # current_dir er allerede defineret i toppen af dit script
        base_data_dir = os.path.join(current_dir, "data")
        date_dir = os.path.join(base_data_dir, today_str)

        # 3. Opret mapperne hvis de ikke findes (exist_ok=True gør, at den ikke crasher hvis mappen findes)
        os.makedirs(date_dir, exist_ok=True)

        # 4. Sammensæt hele stien inklusiv filnavn
        filename = "EN_priser.csv"
        full_path = os.path.join(date_dir, filename)

        # 5. Gem filen
        final_df.to_csv(full_path, sep=",", encoding="utf-8-sig")
        
        print(f"✅ Færdig! Filen er gemt her:")
        print(f"   📂 {full_path}")
    else:
        print("❌ Ingen data fundet.")