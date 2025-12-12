import pandas as pd

def filtrer_priser(input_fil, output_fil):
    # Indlæs CSV-filen
    try:
        df = pd.read_csv(input_fil)
    except FileNotFoundError:
        print(f"Fejl: Kunne ikke finde filen '{input_fil}'")
        return

    # Vælg kun kolonner der indeholder tal (float eller int)
    pris_df = df.select_dtypes(include=['number'])
    
    # Beregn min_pris ud fra disse
    df['min_pris'] = pris_df.min(axis=1)

    # Lav en betingelse: Er 'Football Travel' lig med den laveste pris?
    # Vi tjekker også .notna() for at sikre, at vi ikke sammenligner tomme felter
    er_billigst = (df['Football Travel'] == df['min_pris']) & (df['Football Travel'].notna())
    # Vi beholder rækkerne, hvor Football Travel IKKE (~) er billigst
    df_filtreret = df[~er_billigst].copy()

    # Fjern rækker hvor 'Football Travel' er tom
    er_tom = df['Football Travel'].isna()
    df_filtreret = df_filtreret[~er_tom].copy()

    # Fjern hjælpe-kolonnen 'min_pris' igen, så den ikke kommer med i den nye fil
    df_filtreret = df_filtreret.drop(columns=['min_pris'])

    # Gem resultatet til en ny CSV-fil
    df_filtreret.to_csv(output_fil, index=False)
    
    print(f"Færdig! {len(df) - len(df_filtreret)} rækker blev fjernet.")
    print(f"Resultatet er gemt i '{output_fil}'")

input_navn = 'prissammenligning.csv'
output_navn = 'FT_overpris.csv'

if __name__ == "__main__":
    filtrer_priser(input_navn, output_navn)