import pandas as pd
import numpy as np

def process_football_prices_raw(input_file, output_file):
    # Indlæs data
    df = pd.read_csv(input_file)

    # Reference firma
    ref_agency = 'Football Travel'
    ref_nights_col = 'Football Travel nætter'

    # Find alle andre konkurrenter
    competitors = [
        col for col in df.columns 
        if col != 'Match' 
        and col != ref_agency 
        and 'nætter' not in col
    ]

    output_rows = []

    for index, row in df.iterrows():
        match_name = row['Match']
        ref_nights = row.get(ref_nights_col)
        ref_price = row.get(ref_agency)

        # Start rækken med Match og Football Travel prisen
        new_row = {
            'Match': match_name,
            'Football Travel': ref_price
        }

        # Tjek hver konkurrent
        for comp in competitors:
            comp_nights_col = f"{comp} nætter"
            
            if comp_nights_col in df.columns:
                comp_nights = row.get(comp_nights_col)
                comp_price = row.get(comp)

                # LOGIK: Hvis antallet af nætter er ens, indsæt PRISEN. Ellers tom.
                if pd.notna(ref_nights) and pd.notna(comp_nights) and ref_nights == comp_nights:
                    new_row[comp] = comp_price
                else:
                    new_row[comp] = None
        
        output_rows.append(new_row)

    # Lav DataFrame
    result_df = pd.DataFrame(output_rows)

    # Sørg for rækkefølgen: Match -> Football Travel -> Konkurrenter
    cols = ['Match', 'Football Travel'] + competitors
    # Filtrer kolonner, hvis nogle af konkurrenterne ikke kom med
    cols = [c for c in cols if c in result_df.columns]
    
    result_df = result_df[cols]
    
    # Gem filen
    result_df.to_csv(output_file, index=False)
    print(f"Filen er gemt som: {output_file}")

# Kør funktionen
process_football_prices_raw('EN_priser.csv', 'prissammenligning.csv')