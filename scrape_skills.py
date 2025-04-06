import requests
import json
import re
import yaml
from bs4 import BeautifulSoup
from urllib.parse import urljoin

SKILL_URL = "https://monsterhunterwilds.wiki.fextralife.com/Skills"
# The selector needs escaping for the digit: #wiki-content-block > div.tabcontent.\31 -tab.tabcurrent > div.table-responsive > table
TABLE_SELECTOR = "#wiki-content-block > div.tabcontent.\\31 -tab.tabcurrent > div.table-responsive > table"
OVERRIDE_FILE = "input_overrides.yml"

def fetch_soup(url):
  """Fetches URL and returns BeautifulSoup object."""
  headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
  }
  try:
    response = requests.get(url, headers=headers, timeout=20)
    response.raise_for_status()
    return BeautifulSoup(response.text, 'html.parser')
  except requests.exceptions.RequestException as e:
    print(f"Error fetching {url}: {e}")
    return None

def parse_skill_table(soup, selector):
  """Parses the skill table and extracts data."""
  skill_data = []
  table = soup.select_one(selector)

  if not table:
    print(f"Error: Could not find the table with selector '{selector}'")
    return []

  tbody = table.find('tbody')
  if not tbody:
      print("Error: Could not find tbody within the table.")
      return []

  rows = tbody.find_all('tr')
  print(f"Found {len(rows)} rows in the table body.")

  for row in rows:
    cols = row.find_all('td')
    if len(cols) < 5:  # Expecting at least Name, Type, Desc, Progression, Levels
      continue

    try:
      # --- Extract Name (Column 0) ---
      name_cell = cols[0]
      name_link = name_cell.find('a')
      skill_name = name_link.get_text(strip=True) if name_link else name_cell.get_text(strip=True)
      skill_name = skill_name.replace('\n', ' ').strip()

      if not skill_name or skill_name.lower() == 'name': # Skip header-like rows
          continue

      # --- Extract Max Level (Column 4) ---
      level_cell = cols[4]
      level_text = level_cell.get_text(strip=True)
      # Extract the number from "X levels" or "X level"
      level_match = re.search(r'(\d+)\s+level', level_text, re.IGNORECASE)
      max_level = int(level_match.group(1)) if level_match else 0

      if max_level == 0:
          print(f"Warning: Could not parse max level for '{skill_name}'. Found text: '{level_text}'. Setting level to 0.")
          # Optionally skip if level is crucial, but for now, keep it with 0
          # continue

      skill_data.append({
        "name": skill_name,
        "max_level": max_level
      })

    except Exception as e:
      print(f"Error processing row for skill '{skill_name if 'skill_name' in locals() else 'UNKNOWN'}': {e}")
      print(f"Row content: {row}")
      continue # Skip row on error

  return skill_data

def apply_skill_overrides(skill_data, override_file=OVERRIDE_FILE):
  """Applies overrides from YAML file to the skill data."""
  try:
    with open(override_file, 'r') as f:
      overrides = yaml.safe_load(f)

    if not overrides or 'skills' not in overrides or not overrides['skills']:
      print(f"No skill overrides found or section empty in {override_file}")
      return skill_data

    # Create a dictionary of skills by name for easier lookup
    skill_dict = {s['name']: s for s in skill_data}

    # Apply overrides
    override_count = 0
    added_count = 0
    for override in overrides['skills']:
      if not isinstance(override, dict) or 'name' not in override or 'max_level' not in override:
          print(f"Warning: Skipping invalid skill override format: {override}")
          continue

      name = override['name']
      if name in skill_dict:
        # Replace existing skill
        print(f"Applying override for existing skill: {name}")
        skill_dict[name] = override
        override_count += 1
      else:
        # Add new skill if it doesn't exist
        print(f"Adding new skill from override: {name}")
        skill_dict[name] = override
        added_count += 1

    print(f"Applied {override_count} skill overrides and added {added_count} new skills from {override_file}")

    # Convert dictionary back to list
    return list(skill_dict.values())

  except FileNotFoundError:
    print(f"Override file {override_file} not found. Continuing without overrides.")
    return skill_data
  except yaml.YAMLError as e:
    print(f"Error parsing YAML in {override_file}: {e}")
    return skill_data
  except Exception as e:
    print(f"Unexpected error applying skill overrides: {e}")
    return skill_data


# --- Main Execution ---
if __name__ == "__main__":
  print(f"Fetching skill data from: {SKILL_URL}")
  soup = fetch_soup(SKILL_URL)

  if soup:
    print("Page fetched successfully. Parsing table...")
    all_skill_data = parse_skill_table(soup, TABLE_SELECTOR)

    if all_skill_data:
      print(f"\nSuccessfully parsed {len(all_skill_data)} skills from wiki.")

      # Apply overrides from YAML file
      all_skill_data = apply_skill_overrides(all_skill_data)

      # Sort skills alphabetically by name before saving
      all_skill_data.sort(key=lambda x: x['name'])

      # Save to file, overwriting the old one
      output_filename = "skills_list.json"
      try:
        with open(output_filename, "w") as f:
          # Use compact JSON format (one object per line) as per original file
          f.write("[\n")
          for i, skill in enumerate(all_skill_data):
              f.write(f"  {json.dumps(skill)}")
              if i < len(all_skill_data) - 1:
                  f.write(",\n")
              else:
                  f.write("\n")
          f.write("]\n")
        print(f"Data saved to {output_filename}")
      except IOError as e:
        print(f"Error writing to file {output_filename}: {e}")
    else:
      print("No skill data was parsed. Check the script and website structure.")
  else:
    print("Failed to fetch the page. Cannot parse.")