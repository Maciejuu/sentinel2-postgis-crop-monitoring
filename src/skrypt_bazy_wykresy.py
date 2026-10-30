import psycopg2
import matplotlib

import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# Parametry połączenia z bazą danych
from config import DB_PARAMS

DZIALKA_ID = 16

# Zapytanie SQL
SQL_QUERY = f"""
    SELECT nazwa, uprawa, ndvi_srednie, ndmi_srednie, data_pozyskania
    FROM wskazniki_spektralne
    WHERE dzialka_id = {DZIALKA_ID} AND data_pozyskania BETWEEN '2024-03-01' AND '2024-09-01'
    ORDER BY data_pozyskania;
"""

def fetch_data():
    conn = psycopg2.connect(**DB_PARAMS)
    cur = conn.cursor()
    cur.execute(SQL_QUERY)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def plot_ndvi(data):
    if not data:
        print("Brak danych do wyświetlenia.")
        return

    nazwa, uprawa = data[0][0], data[0][1]
    dates = [row[4] for row in data]
    ndvi_vals = [row[2] for row in data]
    ndmi_vals = [row[3] for row in data]

    plt.figure(figsize=(10, 6))
    plt.plot(dates, ndvi_vals, marker='o', color='green', linestyle='-', label='NDVI')
    plt.plot(dates, ndmi_vals, marker='o', color='blue', linestyle='-', label='NDMI')
    plt.title(f'Zmiany NDVI i NDMI dla działki o nazwie: \"{nazwa}\" (uprawa: {uprawa})')
    plt.xlabel('Data')
    plt.ylabel('Średnie wskaźniki')
    plt.grid(True)
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    plt.gcf().autofmt_xdate()
    plt.tight_layout()
    plt.legend()
    plt.show()

if __name__ == "__main__":
    dane = fetch_data()
    plot_ndvi(dane)