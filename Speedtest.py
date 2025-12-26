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
st.set_page_config(page_title="Football Scraper - Debug Mode", layout="wide")
st.markdown("""
<style>
    div[data-testid="stButton"] > button[kind="primary"] {
        background-color: #28a745 !important;
        border-color: #28a745 !important; 
        color: white !important;
    }
</style>
""", unsafe_allow_html=True)

# --- 1. SETUP CHROME DRIVER ---
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

# --- 2. DIAGNOSTIC MAIN FUNCTION ---
def main():
    st.title("⏱️ Speed Diagnostic Tool")
    st.write("This tool will identify exactly why the app hangs for 30 seconds.")
    
    if st.button("▶️ Run Speed Test", type="primary"):
        st.divider()
        
        # --- TEST 1: The Website Connection ---
        st.subheader("1️⃣ Testing Website Connection")
        st.write("Connecting to `fodboldrejseguiden.dk`...")
        
        start_net = time.time()
        try:
            # We simulate the exact request used to fetch URLs
            headers = {"User-Agent": "Mozilla/5.0"}
            r = requests.get(URL, headers=headers, timeout=35)
            elapsed_net = round(time.time() - start_net, 2)
            
            if elapsed_net > 5:
                st.error(f"❌ SLOW: Website took {elapsed_net} seconds to respond.")
                st.write("**Diagnosis:** The target website is slow or blocking you. You must use caching.")
            else:
                st.success(f"✅ FAST: Website responded in {elapsed_net} seconds.")
        except Exception as e:
            st.error(f"❌ FAILED: Website connection error: {e}")

        st.divider()

        # --- TEST 2: The Browser Startup ---
        st.subheader("2️⃣ Testing Browser Startup")
        st.write("Attempting to launch a single Chrome Driver...")
        
        start_driver = time.time()
        try:
            # This is the exact line that launches the browser
            driver = get_driver()
            elapsed_driver = round(time.time() - start_driver, 2)
            driver.quit()
            
            if elapsed_driver > 5:
                st.error(f"❌ SLOW: Chrome Driver took {elapsed_driver} seconds to launch.")
                st.info("💡 **Diagnosis:** Selenium is timing out trying to download driver updates. You need to download `chromedriver` manually.")
            else:
                st.success(f"✅ FAST: Chrome Driver launched in {elapsed_driver} seconds.")
        except Exception as e:
            st.error(f"❌ FAILED: Driver error: {e}")

if __name__ == "__main__":
    main()