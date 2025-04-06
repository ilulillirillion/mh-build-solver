import requests
import json
from bs4 import BeautifulSoup
from urllib.parse import urljoin

BASE_URL = "https://mhwilds.kiranico.com"
ARMOR_INDEX_URL = urljoin(BASE_URL, "/data/armor-series")

def fetch_soup(url):
  """Fetches URL and returns BeautifulSoup object."""
  try:
    response = requests.get(url, timeout=10)
    response.raise_for_status()  # Raise an exception for bad status codes
    return BeautifulSoup(response.text, 'html.parser')
  except requests.exceptions.RequestException as e:
    print(f"Error fetching {url}: {e}")
    return None

def get_armor_set_urls(index_url):
  """Gets all individual armor set page URLs from the index page."""
  soup = fetch_soup(index_url)
  if not soup:
    return []

  urls = set()
  # Find links within the main content area that point to specific armor series
  # Links look like <a href="/data/armor-series/some-armor">
  # We avoid duplicates and the index page itself.
  # Based on inspection, relevant links are direct children or grandchildren
  # of the main content divs. A simple search for relevant hrefs works.
  for link in soup.find_all('a', href=True):
    href = link['href']
    if href.startswith('/data/armor-series/') and href != '/data/armor-series':
        full_url = urljoin(BASE_URL, href)
        urls.add(full_url)

  print(f"Found {len(urls)} armor set URLs.")
  return list(urls)

def parse_armor_page(url):
  """Parses an individual armor set page and extracts piece data."""
  soup = fetch_soup(url)
  if not soup:
    return []

  armor_pieces_data = []
  set_name_tag = soup.find('h2')
  set_name = set_name_tag.get_text(strip=True) if set_name_tag else "Unknown Set"
  print(f"Parsing armor set: {set_name} ({url})")

  # Find all tables within divs having class 'my-8' which seems to wrap sections
  tables = soup.select('div.my-8 div.relative > table')

  if len(tables) < 3:
      print(f"Warning: Expected at least 3 tables for {set_name}, found {len(tables)}. Skipping.")
      # Try to find tables more robustly if the structure is different
      # This might indicate Low Rank sets or sets with missing pieces
      # For now, we'll skip if the expected structure isn't found
      return [] # Skip if structure is unexpected

  # Table 1: Descriptions (we might not need this now)
  # Table 2: Stats (Defense, Resistances)
  # Table 3: Slots, Skills
  stats_table = tables[1]
  skills_table = tables[2]

  # --- Parse Stats Table ---
  stats_data = {}
  stats_rows = stats_table.find('tbody').find_all('tr')
  if not stats_rows or not stats_rows[0].find('th'): # Check if header row exists
      print(f"Warning: Stats table header not found for {set_name}. Skipping.")
      return []
      
  # Skip header row (index 0)
  for row in stats_rows[1:]:
    cols = row.find_all(['td', 'th']) # Header sometimes uses th
    if len(cols) < 8: continue # Expecting Slot Type, Name, Def, Res*5

    piece_type = cols[0].get_text(strip=True)
    piece_name = cols[1].get_text(strip=True)
    defense = cols[2].get_text(strip=True)
    fire_res = cols[3].get_text(strip=True)
    water_res = cols[4].get_text(strip=True)
    thunder_res = cols[5].get_text(strip=True)
    ice_res = cols[6].get_text(strip=True)
    dragon_res = cols[7].get_text(strip=True)

    stats_data[piece_name] = {
        "type": piece_type,
        "defense": int(defense) if defense.isdigit() else 0,
        "fire_res": int(fire_res) if fire_res.isdigit() else 0,
        "water_res": int(water_res) if water_res.isdigit() else 0,
        "thunder_res": int(thunder_res) if thunder_res.isdigit() else 0,
        "ice_res": int(ice_res) if ice_res.isdigit() else 0,
        "dragon_res": int(dragon_res) if dragon_res.isdigit() else 0,
    }

  # --- Parse Skills/Slots Table ---
  skills_rows = skills_table.find('tbody').find_all('tr')
  if not skills_rows or not skills_rows[0].find('th'): # Check if header row exists
      print(f"Warning: Skills table header not found for {set_name}. Skipping.")
      return []

  # Skip header row (index 0)
  for row in skills_rows[1:]:
    cols = row.find_all(['td', 'th'])
    if len(cols) < 4: continue # Expecting Slot Type, Name, Slots, Skills

    piece_name = cols[1].get_text(strip=True)
    slots_text = cols[2].get_text(strip=True) # e.g., "[1][1][0]"
    skills_tags = cols[3].find_all('a') # Skills are links

    # Parse slots: Count occurrences of [1], [2], [3], [4]
    slots = {
        "level_1": slots_text.count('[1]'),
        "level_2": slots_text.count('[2]'),
        "level_3": slots_text.count('[3]'),
        "level_4": slots_text.count('[4]'),
    }

    skills = []
    for skill_tag in skills_tags:
        skill_text = skill_tag.get_text(strip=True) # e.g., "Attack Boost +2"
        skill_name = skill_text.split('+')[0].strip()
        skill_level = int(skill_text.split('+')[1]) if '+' in skill_text else 1
        skills.append({"name": skill_name, "level": skill_level})

    # Combine with stats data
    if piece_name in stats_data:
        armor_piece = {
            "set_name": set_name,
            "piece_name": piece_name,
            **stats_data[piece_name], # Merge stats dict
            "slots": slots,
            "skills": skills
        }
        armor_pieces_data.append(armor_piece)
    else:
        print(f"Warning: Mismatch finding stats for piece '{piece_name}' in set '{set_name}'")


  return armor_pieces_data

# --- Main Execution ---
if __name__ == "__main__":
  all_armor_data = []
  armor_set_urls = get_armor_set_urls(ARMOR_INDEX_URL)

  # Limit for testing, remove later
  # armor_set_urls = armor_set_urls[:5] 

  for url in armor_set_urls:
    set_data = parse_armor_page(url)
    if set_data:
      all_armor_data.extend(set_data)

  # Output the data (e.g., print as JSON)
  # print("\n--- Collected Armor Data ---")
  # print(json.dumps(all_armor_data, indent=2))

  # Optionally, save to a file
  with open("armor_data.json", "w") as f:
    json.dump(all_armor_data, f, indent=2)
  print("\nData saved to armor_data.json")
