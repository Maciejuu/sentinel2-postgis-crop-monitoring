import psycopg2
import rasterio
import numpy as np
import matplotlib
import matplotlib.pyplot as plt

from rasterio.io import MemoryFile
from rasterio.mask import mask
import json

# --- Parametry bazy danych ---
from config import DB_PARAMS

# --- Parametry zapytania ---
DZIALKA_ID = 12
DATA_POZYSKANIA = '2024-07-10'

def fetch_raster_and_geometry():
    with psycopg2.connect(**DB_PARAMS) as conn:
        with conn.cursor() as cur:
            # Pobranie rastra NDVI
            cur.execute("""
                SELECT ST_AsGDALRaster(rast, 'GTiff')
                FROM ndvi
                WHERE data_pozyskania = %s
                LIMIT 1;
            """, (DATA_POZYSKANIA,))
            raster_data = cur.fetchone()
            if not raster_data:
                raise Exception("Raster NDVI nie został znaleziony.")
            raster_bytes = raster_data[0].tobytes()

            #Geometria działki i transformacja do układu EPSG:32634
            cur.execute("""
                SELECT ST_AsGeoJSON(ST_Transform(geom, 32634))
                FROM dzialki
                WHERE id = %s;
            """, (DZIALKA_ID,))
            geom_data = cur.fetchone()
            if not geom_data:
                raise Exception("Działka nie została znaleziona.")
            geometry = json.loads(geom_data[0])

            return raster_bytes, [geometry]

def fetch_min_max_ndvi(data_pozyskania):
    with psycopg2.connect(**DB_PARAMS) as conn:
        with conn.cursor() as cur:
            # Pobierz min i max wartości z rastra NDVI dla danej daty
            cur.execute("""
                SELECT (stats).min, (stats).max
                FROM (
                    SELECT ST_SummaryStats(rast, 1, TRUE) AS stats
                    FROM ndvi
                    WHERE data_pozyskania = %s
                    LIMIT 1
                ) sub;
            """, (data_pozyskania,))
            result = cur.fetchone()
            if result is None:
                raise Exception("Nie znaleziono statystyk dla rastra NDVI.")
            return result[0], result[1]  # min, max

def visualize_ndvi(raster_bytes, geometry, vmin, vmax):
    with MemoryFile(raster_bytes) as memfile:
        with memfile.open() as src:
            # Przycięcie rastrowe do granicy działki
            clipped_raster, _ = mask(src, geometry, crop=True)
            ndvi = clipped_raster[0].astype(float)
            ndvi[ndvi == src.nodata] = np.nan

            # Wizualizacja
            plt.figure(figsize=(8, 6))
            cmap = plt.cm.RdYlGn  # Zielono-żółta skala
            plt.imshow(ndvi, cmap=cmap, vmin=vmin, vmax=vmax)
            plt.colorbar(label='NDVI')
            plt.title(f"NDVI dla działki {DZIALKA_ID} z dnia {DATA_POZYSKANIA}")
            plt.tight_layout()
            plt.show()


if __name__ == "__main__":
    try:
        raster_bytes, geometry = fetch_raster_and_geometry()
        vmin, vmax = fetch_min_max_ndvi(DATA_POZYSKANIA)
        print(f"Min NDVI: {vmin}, Max NDVI: {vmax}")
        visualize_ndvi(raster_bytes, geometry, vmin, vmax)
    except Exception as e:
        print(f"Błąd: {e}")