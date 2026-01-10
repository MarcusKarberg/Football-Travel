import streamlit as st
import pandas as pd
import io
import os
import time
import subprocess
import sys
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright"])
subprocess.run(["playwright", "install", "chromium"])
from datetime import datetime, timedelta
from openpyxl.styles import Border, Side, PatternFill, Font
from openpyxl.utils import get_column_letter

# --- IMPORTER VORES MODULER ---
import Footballtravel    
import Olka  
import Fodboldrejseguiden  

st.set_page_config(page_title="Football Scraper Pro", layout="wide")

# Styling
st.markdown("""
<style>
    div[data-testid="stButton"] > button[kind="primary"] {
        background-color: #28a745 !important;
        border-color: #28a745 !important; 
        color: white !important;
    }
</style>
""", unsafe_allow_html=True)

def get_club_names():
    if not os.path.exists("club_names.xlsx"):
        st.error("❌ Mangler 'club_names.xlsx'")
        return []
    try:
        return pd.read_excel("club_names.xlsx", sheet_name="EN", usecols="A", header=None)[0].dropna().astype(str).str.strip().tolist()
    except: return []

def main():
    st.title("⚽ Prissammenligning: Billet + Hotel")
    
    excel_clubs = get_club_names()
    if "selected_clubs" not in st.session_state: st.session_state.selected_clubs = set()

    # Vælg klubber
    cols = st.columns(4)
    for i, club in enumerate(excel_clubs):
        if cols[i%4].button(club, key=club, type="primary" if club in st.session_state.selected_clubs else "secondary", use_container_width=True):
            if club in st.session_state.selected_clubs: st.session_state.selected_clubs.remove(club)
            else: st.session_state.selected_clubs.add(club)
            st.rerun()

    selected = list(st.session_state.selected_clubs)

    if selected:
        st.divider()
        if st.button("🔎 Søg efter priser", type="primary"):
                    # --- START TIMER ---
            start_time = time.time()  # <--- Added this to capture start time
            
            P_FT = 60   # Hurtig (CSV)
            P_OLKA = 450 # Langsom (Browser)
            P_FRG = 300  # Langsom (Browser)
            
            total_points = P_FT + P_OLKA + P_FRG
            current_points = 0
            
            # 2. OPRET PROGRESS BAR
            progress_bar = st.progress(0, text="Starter søgning...")
            current_points += P_FT
            progress_bar.progress(current_points / total_points)

            status = st.status("Arbejder...", expanded=True)
            
            # --- 1. Hent fra FootballTravel (CSV) ---
            status.write("🤓Data fra Footballtravel")
            try:
                df1 = Footballtravel.get_prices(selected)
                if not df1.empty:
                    df1['Provider'] = "Footballtravel.dk"
                st.toast(f"Footballtravel: {len(df1)} tilbud fundet", icon="✅")
            except Exception as e:
                st.error(f"Fejl i Footballtravel: {e}")
                df1 = pd.DataFrame()

            current_points += P_FT
            progress_bar.progress(current_points / total_points, text="Footballtravel færdig. Starter Olka...")
            
            # --- 2. Hent fra Olka (Selenium/Playwright) ---
            status.write("🌐 Data fra Olka")
            try:
                df2 = Olka.get_prices(selected)
                if not df2.empty:
                    st.toast(f"Olka: {len(df2)} tilbud fundet", icon="✅")
                else:
                    st.toast("Olka: Ingen tilbud fundet", icon="⚠️")
            except Exception as e:
                st.error(f"Fejl i OLKA: {e}")
                df2 = pd.DataFrame()
            
            current_points += P_OLKA
            progress_bar.progress(current_points / total_points, text="Olka færdig. Starter resterende...")

            # --- 3. Hent fra Fodboldrejseguiden (Selenium) ---
            status.write("👽 Data fra de resterende")
            try:
                df5 = Fodboldrejseguiden.get_prices(selected)
                st.toast(f"Fodboldrejseguiden: {len(df5)} tilbud fundet", icon="✅")
            except Exception as e:
                st.error(f"Fejl i Fodboldrejseguiden: {e}")
                df5 = pd.DataFrame()
            
            current_points += P_FRG
            progress_bar.progress(1.0, text="Færdig!")

                    # --- STOP TIMER ---
            end_time = time.time()               # <--- Capture end time
            elapsed_time = end_time - start_time # <--- Calculate difference
            minutes = int(elapsed_time // 60)
            seconds = int(elapsed_time % 60)
                    # Update status with time
            status.update(label=f"Færdig! (Tid: {minutes}m {seconds}s)", state="complete", expanded=False)
            st.success(f"✅ Søgning gennemført på {minutes} minutter og {seconds} sekunder.")

            status.update(label="Færdig!", state="complete", expanded=False)

            # --- 4. SAML DATA ---
            # Nu hvor alle 3 er kørt, samler vi dem i én liste
            frames = [df1, df2, df5]
            
            if all(df.empty for df in frames):
                st.warning("Ingen priser fundet hos nogen udbydere.")
                st.stop()
            
            full_df = pd.concat(frames, ignore_index=True)

            # --- 5. DATA RENSNING & FLETNING ---
            full_df['Provider'] = full_df['Provider'].fillna("Ukendt").astype(str)
            full_df = full_df[full_df['Provider'].str.strip() != ""]

            # Konverter datoer
            full_df['SortDate'] = pd.to_datetime(full_df['SortDate'], errors='coerce')
            full_df = full_df.dropna(subset=['SortDate'])

            # FILTER: Fjern kampe indenfor 24 timer
            now = datetime.now()
            cutoff_time = now + timedelta(hours=24)
            full_df = full_df[full_df['SortDate'] > cutoff_time]

            if full_df.empty:
                st.warning("Ingen kampe fundet længere end 24 timer frem.")
                st.stop()

            # Sorter data
            full_df = full_df.sort_values(by=['Club', 'SortDate'])

            # Logik: Fuzzy Match
            full_df['club_change'] = full_df['Club'] != full_df['Club'].shift()
            full_df['date_diff'] = full_df['SortDate'].diff().dt.days.abs()
            full_df['big_gap'] = full_df['date_diff'] > 2 

            # Tildel ID
            full_df['Match_Group_ID'] = (full_df['club_change'] | full_df['big_gap']).cumsum()

            # --- 6. PIVOT OG FORMATERING ---
            group_meta = full_df.groupby('Match_Group_ID').agg({
                'Club': 'first',
                'Match': lambda x: max(x, key=len), 
                'SortDate': 'first'
            })

            group_meta['Date_Str'] = group_meta['SortDate'].dt.strftime('%d/%m')
            group_meta['Match_Display'] = group_meta['Match'] + " (" + group_meta['Date_Str'] + ")"

            # Pivot tabeller
            pivot_price = full_df.pivot_table(index='Match_Group_ID', columns='Provider', values='Price', aggfunc='min')
            pivot_nights = full_df.pivot_table(index='Match_Group_ID', columns='Provider', values='Nights', aggfunc='max')

            # Byg DataFrame
            final_df = pd.DataFrame(index=group_meta.index)
            final_df['Club'] = group_meta['Club']
            final_df['SortDate'] = group_meta['SortDate']
            final_df['Match_Display'] = group_meta['Match_Display']

            # --- VIGTIGT: SORTERING AF UDBYDERE ---
            all_providers = sorted(full_df['Provider'].unique())
            
            # Tving "Footballtravel.dk" (CSV-kilden) frem som nr. 1
            pri_provider = "Footballtravel.dk"
            if pri_provider in all_providers:
                all_providers.remove(pri_provider)
                all_providers.insert(0, pri_provider)

            # Indsæt kolonner
            for prov in all_providers:
                if prov in pivot_price:
                    final_df[prov] = pivot_price[prov].fillna(0).astype(int)
                    final_df[f"{prov} nætter"] = pivot_nights[prov].fillna(0).astype(int)

            # Endelig sortering af rækker
            final_df = final_df.sort_values(by=['Club', 'SortDate'])

            # Klargør til Excel
            export_df = final_df.copy()
            ordered_clubs = export_df['Club'].tolist()
            
            excel_data = export_df.drop(columns=['Club', 'SortDate'])
            cols = ['Match_Display'] + [c for c in excel_data.columns if c != 'Match_Display']
            excel_data = excel_data[cols]

            # --- 7. EXCEL GENERERING ---
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                excel_data.to_excel(writer, sheet_name='Prices', startrow=2)
                ws = writer.sheets['Prices']
                
                ws['A1'] = "Prices: Ticket + Hotel"
                ws['A1'].font = Font(size=16, bold=True)
                ws.column_dimensions['A'].width = 40
                
                for col_idx, col_name in enumerate(excel_data.columns, 2):
                    col_letter = get_column_letter(col_idx)
                    ws.column_dimensions[col_letter].width = 20

                thick_border = Border(top=Side(style='medium'))
                
                for i, club in enumerate(ordered_clubs):
                    row = i + 4
                    if i > 0 and club != ordered_clubs[i-1]:
                        for cell in ws[row]: cell.border = thick_border
                
                # Farver
                price_cols_indices = []
                for idx, col_name in enumerate(excel_data.columns, 2):
                    if "nætter" not in str(col_name).lower() and col_name != "Match_Display":
                        price_cols_indices.append(idx)

                green_fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
                red_fill = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")

                for r in range(4, 4 + len(ordered_clubs)):
                    row_prices = []
                    for c_idx in price_cols_indices:
                        val = ws.cell(row=r, column=c_idx).value
                        if isinstance(val, (int, float)) and val > 0:
                            row_prices.append(val)
                    
                    if row_prices:
                        min_p = min(row_prices)
                        max_p = max(row_prices)
                        for c_idx in price_cols_indices:
                            cell = ws.cell(row=r, column=c_idx)
                            val = cell.value
                            if isinstance(val, (int, float)) and val > 0:
                                if val == min_p: cell.fill = green_fill
                                if val == max_p and len(row_prices) > 1: cell.fill = red_fill

            # Download
            timestamp = datetime.now().strftime("%H-%M")
            st.download_button("📥 Download Excel", output.getvalue(), f"prices_{timestamp}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            
            st.dataframe(excel_data, use_container_width=True)

if __name__ == "__main__":
    main()