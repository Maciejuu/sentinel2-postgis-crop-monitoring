import os
import shutil
import zipfile
import psycopg2
import geopandas as gpd
import xml.etree.ElementTree as ET
import subprocess

# === KONFIGURACJA DOSTĘPU DO BAZY DANYCH ===
from config import DB_PARAMS

from config import SHAPEFILE_PATH, EXTRACT_DIR, RASTER_SRID, ZOBRAZOWANIA_DIR, require_import_permission

# === IMPORT DZIAŁEK ===
def import_dzialki():
    gdf = gpd.read_file(SHAPEFILE_PATH)
    gdf = gdf.to_crs(epsg=2180)
    insert_sql = """
    DROP TABLE IF EXISTS dzialki;
    CREATE TABLE dzialki (
        id SERIAL PRIMARY KEY,
        nazwa TEXT,
        pow REAL,
        uprawa TEXT,
        nr_dzialek TEXT,
        naz_obreb TEXT,
        nr_obreb TEXT,
        geom GEOMETRY(POLYGON, 2180)
    );
    """
    run_sql(insert_sql)

    insert_geom_sql = "INSERT INTO dzialki (id, nazwa, pow, uprawa, nr_dzialek, naz_obreb, nr_obreb, geom) VALUES (%s, %s, %s, %s, %s, %s, %s, ST_GeomFromText(%s, 2180));"

    rows = [
        (
            int(row.id), row.Nazwa, row.Pow, row.Uprawa, row.Nr_dzialek, row.Naz_obreb, row.Nr_obreb, row.geometry.wkt
        ) for _, row in gdf.iterrows()
    ]
    with psycopg2.connect(**DB_PARAMS) as conn:
        with conn.cursor() as cur:
            cur.executemany(insert_geom_sql, rows)
            conn.commit()

    run_sql("UPDATE dzialki SET geom = ST_SetSRID(geom, 2180) WHERE ST_SRID(geom) = 0;")

# === ZNAJDOWANIE POTRZEBNYCH PASM W ZOBRAZOWANIU===
def find_band(band_id):
    for root, _, files in os.walk(EXTRACT_DIR):
        for file in files:
            if band_id in file and file.endswith('.jp2'):
                return os.path.join(root, file)
    return None

# === POBRANIE DATY ZOBRAZOWANIA Z METADANYCH ===
def extract_date_from_metadata():
    for root, _, files in os.walk(EXTRACT_DIR):
        for file in files:
            if file.endswith('MTD_TL.xml') or file.endswith('MTD_MSIL1C.xml'):
                full_path = os.path.join(root, file)
                tree = ET.parse(full_path)
                root_elem = tree.getroot()
                for elem in root_elem.iter():
                    if 'SENSING_TIME' in elem.tag and elem.text:
                        return elem.text[:10]
    return None

# === IMPORT RASTRA DO BAZY ===
def import_raster_to_db(file_path, pasmo, data_pozyskania):
    nazwa_pliku = os.path.basename(file_path)

    check_sql = """SELECT 1 FROM zobrazowania_raster WHERE nazwa_pliku = %s LIMIT 1;"""

    with psycopg2.connect(**DB_PARAMS) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS zobrazowania_raster (
                    rid SERIAL PRIMARY KEY,
                    data_pozyskania DATE,
                    kanal TEXT,
                    nazwa_pliku TEXT,
                    rast RASTER
                );
            """)
            conn.commit()

            cur.execute(check_sql, (nazwa_pliku,))
            if cur.fetchone():
                print(f"Plik {nazwa_pliku} już znajduje się w bazie – pomijam import.")
                return

    # Ustawienia środowiska z hasłem
    env = os.environ.copy()
    env["PGPASSWORD"] = DB_PARAMS["password"]

    # Komenda importująca raster
    cmd = ["raster2pgsql", "-s", RASTER_SRID, "-I", "-M", "-t", "1024x1024", "-a", file_path, "public.zobrazowania_raster"]

    # pipe: raster2pgsql | psql
    psql_cmd = ["psql", "-h", DB_PARAMS["host"], "-p", str(DB_PARAMS["port"]), "-v", "ON_ERROR_STOP=1", "-d", DB_PARAMS["dbname"], "-U", DB_PARAMS["user"]]

    # Uruchomienie potoku raster2pgsql | psql
    raster_proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, env=env)
    psql_proc = subprocess.Popen(psql_cmd, stdin=raster_proc.stdout, env=env)
    raster_proc.stdout.close()
    psql_proc.communicate()
    raster_proc.wait()
    if psql_proc.returncode or raster_proc.returncode:
        raise RuntimeError("Raster import failed; metadata was not updated.")

    # Dodanie metadanych po imporcie
    with psycopg2.connect(**DB_PARAMS) as conn:
        with conn.cursor() as cur:
            update_sql = f"""
                UPDATE zobrazowania_raster
                SET data_pozyskania = %s,
                    kanal = %s,
                    nazwa_pliku = %s
                WHERE data_pozyskania IS NULL AND kanal IS NULL;
            """
            cur.execute(update_sql, (data_pozyskania, pasmo.upper(), nazwa_pliku))
            conn.commit()

    print(f"Raster {nazwa_pliku} został zaimportowany do tabeli zobrazowania_raster.")

def usun_puste_kafle(DB_PARAMS):

    sql = f"""
        DELETE FROM zobrazowania_raster r
        WHERE NOT EXISTS (
            SELECT 1
            FROM dzialki d
            WHERE ST_Intersects(
                ST_Transform(d.geom, {RASTER_SRID}),
                r.rast
            )
        );
    """

    try:
        with psycopg2.connect(**DB_PARAMS) as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                deleted = cur.rowcount
                conn.commit()
                print(f"Usunięto {deleted} niepokrywających kafli rastrowych.")
    except Exception as e:
        raise RuntimeError("Database processing failed.") from None

def scal_kafle(DB_PARAMS):
    sql = """
        CREATE TABLE IF NOT EXISTS zobrazowania (
            id SERIAL PRIMARY KEY,
            kanal TEXT,
            data_pozyskania DATE,
            nazwa TEXT UNIQUE,
            rast RASTER
        );

        INSERT INTO zobrazowania (kanal, data_pozyskania, nazwa, rast)
        SELECT 
            kanal,
            data_pozyskania,
            to_char(data_pozyskania, 'YYYYMMDD') || '_' || kanal AS nazwa,
            ST_Union(rast)
        FROM zobrazowania_raster
        GROUP BY kanal, data_pozyskania
        ON CONFLICT (nazwa) DO NOTHING;
    """

    try:
        with psycopg2.connect(**DB_PARAMS) as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                conn.commit()
                print("Tabela 'zobrazowania' została uzupełniona.")
    except Exception as e:
        raise RuntimeError("Database processing failed.") from None

# === POŁĄCZENIE DB I WYSYŁANIE SQL ===
def run_sql(sql, params=None):
    with psycopg2.connect(**DB_PARAMS) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            conn.commit()

# Funkcja do inicjalizacji tabeli metadanych
def initialize_metadata_table():
    with psycopg2.connect(**DB_PARAMS) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS zobrazowania_info (
                    id SERIAL PRIMARY KEY,
                    nazwa_pliku TEXT UNIQUE,
                    data_pozyskania DATE,
                    sciezka TEXT,
                    status TEXT DEFAULT 'nowy'
                );
            """)
            conn.commit()

def check_if_processed(zip_file):
    with psycopg2.connect(**DB_PARAMS) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 1 FROM zobrazowania_info WHERE nazwa_pliku = %s AND status = 'przetworzono'
            """, (zip_file,))
            return cur.fetchone() is not None

def mark_as_processed(zip_file, data_pozyskania):
    with psycopg2.connect(**DB_PARAMS) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO zobrazowania_info (nazwa_pliku, data_pozyskania, sciezka, status)
                VALUES (%s, %s, %s, 'przetworzono')
                ON CONFLICT (nazwa_pliku) DO UPDATE SET status = 'przetworzono', data_pozyskania = EXCLUDED.data_pozyskania;
            """, (zip_file, data_pozyskania, os.path.join(ZOBRAZOWANIA_DIR, zip_file)))
            conn.commit()

# === GŁÓWNA LOGIKA ===
def main():
    require_import_permission()
    os.makedirs(EXTRACT_DIR, exist_ok=True)
    import_dzialki()
    initialize_metadata_table()

    for file in os.listdir(ZOBRAZOWANIA_DIR):
        if file.endswith('.zip'):
            zip_path = os.path.join(ZOBRAZOWANIA_DIR, file)
            print(f"\n--- Przetwarzanie pliku: {file} ---")

            if check_if_processed(file):
                print(f"Plik {file} już przetworzony.")
                continue

            for f in os.listdir(EXTRACT_DIR):
                f_path = os.path.join(EXTRACT_DIR, f)
                if os.path.isfile(f_path) or os.path.islink(f_path):
                    os.unlink(f_path)
                elif os.path.isdir(f_path):
                    shutil.rmtree(f_path)

            # 1. Wypakowanie
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(EXTRACT_DIR)

            # 2. Znalezienie pasm
            red_orig = find_band("B04")
            nir_orig = find_band("B08")
            swir_orig = find_band("B11")
            if not red_orig or not swir_orig or not nir_orig:
                print("Nie znaleziono wymaganych pasm – pominięto.")
                continue

            # 3. Data
            date_str = extract_date_from_metadata()
            if not date_str:
                print("Nie można wyodrębnić daty – pominięto.")
                continue

            # 4. Import rastrów
            import_raster_to_db(red_orig, 'B04', date_str)
            import_raster_to_db(nir_orig, 'B08', date_str)
            import_raster_to_db(swir_orig, 'B11', date_str)

            # 5. Czyszczenie + scalanie
            usun_puste_kafle(DB_PARAMS)
            scal_kafle(DB_PARAMS)  # Nazwa zmieniona w tej funkcji niżej

            # 6. NDVI
            run_sql("""
                CREATE TABLE IF NOT EXISTS ndvi (
                    id SERIAL PRIMARY KEY,
                    data_pozyskania DATE UNIQUE,
                    rast RASTER
                );
            """)

            run_sql("""
                CREATE TABLE IF NOT EXISTS ndmi (
                    id SERIAL PRIMARY KEY,
                    data_pozyskania DATE UNIQUE,
                    rast RASTER
                );
            """)

            run_sql("""
                INSERT INTO ndvi (data_pozyskania, rast)
                SELECT 
                    b4.data_pozyskania,
                    ST_MapAlgebraExpr(b8.rast, b4.rast, 
                        '( [rast1.val] - [rast2.val] )::float / ( [rast1.val] + [rast2.val] )', '32BF')
                FROM zobrazowania b4
                JOIN zobrazowania b8
                ON b4.data_pozyskania = b8.data_pozyskania
                WHERE b4.kanal = 'B04' AND b8.kanal = 'B08'
                AND NOT EXISTS (
                    SELECT 1 FROM ndvi n WHERE n.data_pozyskania = b4.data_pozyskania
                );
            """)

            run_sql("""
                INSERT INTO ndmi (data_pozyskania, rast)
                SELECT 
                    b8.data_pozyskania,
                    ST_MapAlgebraExpr(ST_Resample(b8.rast, b11.rast), b11.rast, 
                        '( [rast1.val] - [rast2.val] )::float / ( [rast1.val] + [rast2.val] )', '32BF')
                FROM zobrazowania b8
                JOIN zobrazowania b11
                ON b8.data_pozyskania = b11.data_pozyskania
                WHERE b8.kanal = 'B08' AND b11.kanal = 'B11'
                AND NOT EXISTS (
                    SELECT 1 FROM ndmi n WHERE n.data_pozyskania = b8.data_pozyskania
                );
            """)

            # 7. Wskazniki spektralne
            run_sql("""
                CREATE TABLE IF NOT EXISTS wskazniki_spektralne (
                    dzialka_id INT,
                    nazwa TEXT,
                    uprawa TEXT,
                    data_pozyskania DATE,
                    ndvi_srednie NUMERIC(5, 3),
                    ndmi_srednie NUMERIC(5, 3)
                );
            """)

            run_sql("""
                INSERT INTO wskazniki_spektralne (
                    dzialka_id, nazwa, uprawa, data_pozyskania, ndvi_srednie, ndmi_srednie
                )
                SELECT 
                    d.id,
                    d.nazwa,
                    d.uprawa,
                    n.data_pozyskania,
                    ROUND(AVG((stats_ndvi).mean)::numeric, 3) AS ndvi_srednie,
                    ROUND(AVG((stats_ndmi).mean)::numeric, 3) AS ndmi_srednie
                FROM dzialki d
                JOIN ndvi n ON TRUE
                JOIN ndmi m ON m.data_pozyskania = n.data_pozyskania
                CROSS JOIN LATERAL ST_SummaryStats(ST_Clip(n.rast, ST_Transform(d.geom, 32634), true)) AS stats_ndvi
                CROSS JOIN LATERAL ST_SummaryStats(ST_Clip(m.rast, ST_Transform(d.geom, 32634), true)) AS stats_ndmi
                WHERE NOT EXISTS (SELECT 1 FROM wskazniki_spektralne ns WHERE ns.dzialka_id = d.id AND ns.data_pozyskania = n.data_pozyskania)
                GROUP BY d.id, d.nazwa, d.uprawa, n.data_pozyskania;
            """)

            mark_as_processed(file, date_str)

    run_sql("""DROP TABLE IF EXISTS zobrazowania_raster;""")

if __name__ == '__main__':
    main()