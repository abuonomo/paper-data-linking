from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
import pandas as pd  # Key Change: Import pandas

# Step 1: Set up Selenium with headless Chrome
options = Options()
options.add_argument('--headless')
options.add_argument('--disable-gpu')
driver = webdriver.Chrome(options=options)  # Ensure chromedriver is installed and in your PATH

try:
    # Step 2: Load the page
    url = "https://heliodata-staging2.heliophysics.net/missionlist"
    driver.get(url)

    # Step 3: Wait for the table to load (adjust timeout if needed)
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.CLASS_NAME, "missionlist-table"))
    )

    # Step 4: Parse the rendered HTML using BeautifulSoup
    soup = BeautifulSoup(driver.page_source, "html.parser")
    table = soup.find("table", class_="missionlist-table")

    if table:
        rows = table.find_all("tr")[1:]  # Skip header row
        missions = []
        for row in rows:
            cells = row.find_all("td")
            if len(cells) >= 2:
                mission_id = cells[0].get_text(strip=True)
                mission_name = cells[1].get_text(strip=True)
                missions.append({"mission_id": mission_id, "mission_name": mission_name})

        # Key Change: Create a pandas DataFrame and save the data to a CSV file
        df = pd.DataFrame(missions)
        df.to_csv("missions.csv", index=False)
        print("Data saved to missions.csv")
    else:
        print("Table not found.")

finally:
    driver.quit()
