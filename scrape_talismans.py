import requests
import json
import re
import yaml
from bs4 import BeautifulSoup
from urllib.parse import urljoin

TALISMAN_URL = "https://monsterhunterwilds.wiki.fextralife.com/Talismans"
TABLE_SELECTOR = "#wiki-content-block > div.tabcontent.table-tab.tabcurrent > div.table-responsive > table"

def fetch_soup(url):
  """Fetches URL and returns BeautifulSoup object."""
  headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
  }
  try:
    # Fextralife often requires a realistic User-Agent
    response = requests.get(url, headers=headers, timeout=20)
    response.raise_for_status()
    return BeautifulSoup(response.text, 'html.parser')
  except requests.exceptions.RequestException as e:
    print(f"Error fetching {url}: {e}")
    return None

def parse_talisman_table(soup, selector):
  """Parses the talisman table and extracts data."""
  talisman_data = []
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
    if len(cols) < 3:  # Expecting at least Name, Rarity, Skill(s)
      # print(f"Skipping row, not enough columns: {row}")
      continue

    try:
      # --- Extract Name (Column 0) ---
      # Name might be within an <a> tag or just text
      name_tag = cols[0].find('a')
      talisman_name = name_tag.get_text(strip=True) if name_tag else cols[0].get_text(strip=True)
      talisman_name = talisman_name.replace('\n', ' ').strip() # Clean up potential newlines

      if not talisman_name or talisman_name.lower() == 'name': # Skip header-like rows
          continue

      # --- Extract Rarity (Column 1) ---
      # Rarity might be text or inside other tags
      rarity_text = cols[1].get_text(strip=True)
      # Try to extract a number, handling potential non-digit characters
      rarity_match = re.search(r'\d+', rarity_text)
      rarity = int(rarity_match.group(0)) if rarity_match else 0
      if rarity == 0:
          print(f"Warning: Could not parse rarity for '{talisman_name}'. Found text: '{rarity_text}'. Setting rarity to 0.")


      # --- Extract Skills (Column 2 onwards, potentially) ---
      skills = []
      # Fextra often puts skills in the 3rd column (index 2)
      # Sometimes separated by <br> or just listed
      skill_col_index = 2
      # The skill information is in the 4th column (index 3), not the 3rd column (index 2)
      skill_col_index = 3
      
      if len(cols) > skill_col_index:
          skill_cell = cols[skill_col_index]
          skill_text = skill_cell.get_text(strip=True)
          
          # Find the skill link (contains the skill name)
          skill_link = skill_cell.find('a')
          if skill_link:
              skill_name = skill_link.get_text(strip=True)
              
              # Extract level from text like "Skill Name Lv X" or similar patterns
              level_match = re.search(r'Lv\s*(\d+)', skill_text)
              if level_match:
                  skill_level = int(level_match.group(1))
              else:
                  # Fallback: try to find any number at the end of the text
                  level_match = re.search(r'(\d+)$', skill_text)
                  skill_level = int(level_match.group(1)) if level_match else 1
              
              skills.append({"name": skill_name, "points": skill_level})
          else:
              print(f"Warning: Could not find skill link in cell for '{talisman_name}'")

          # # Rename 'level' key to 'points' to match target format - Done inline now
          # for skill in skills:
          #     if 'level' in skill:
          #         skill['points'] = skill.pop('level')

          # Rename 'level' key to 'points' to match target format
          for skill in skills:
              if 'level' in skill:
                  skill['points'] = skill.pop('level')

      if not skills:
          print(f"Warning: No skills found or parsed for '{talisman_name}'.")
          # Decide whether to skip or add with empty skills
          # continue # Option: skip talismans with no parsed skills

      talisman_data.append({
        "name": talisman_name,
        "rarity": rarity,
        "skills": skills
      })

    except Exception as e:
      print(f"Error processing row for talisman '{talisman_name if 'talisman_name' in locals() else 'UNKNOWN'}': {e}")
      print(f"Row content: {row}")
      continue # Skip row on error

  return talisman_data

def apply_overrides(talisman_data, override_file="input_overrides.yml"):
  """Applies overrides from YAML file to the talisman data."""
  try:
    with open(override_file, 'r') as f:
      overrides = yaml.safe_load(f)
    
    if not overrides or 'talismans' not in overrides or not overrides['talismans']:
      print(f"No talisman overrides found in {override_file}")
      return talisman_data
    
    # Create a dictionary of talismans by name for easier lookup
    talisman_dict = {t['name']: t for t in talisman_data}
    
    # Apply overrides
    override_count = 0
    for override in overrides['talismans']:
      if 'name' not in override:
        print("Warning: Skipping override without a name")
        continue
      
      name = override['name']
      if name in talisman_dict:
        # Replace existing talisman
        print(f"Applying override for existing talisman: {name}")
        talisman_dict[name] = override
      else:
        # Add new talisman
        print(f"Adding new talisman from override: {name}")
        talisman_dict[name] = override
      override_count += 1
    
    print(f"Applied {override_count} talisman overrides from {override_file}")
    
    # Convert dictionary back to list
    return list(talisman_dict.values())
  
  except FileNotFoundError:
    print(f"Override file {override_file} not found. Continuing without overrides.")
    return talisman_data
  except yaml.YAMLError as e:
    print(f"Error parsing YAML in {override_file}: {e}")
    return talisman_data
  except Exception as e:
    print(f"Unexpected error applying overrides: {e}")
    return talisman_data

# --- Main Execution ---
if __name__ == "__main__":
  print(f"Fetching talisman data from: {TALISMAN_URL}")
  soup = fetch_soup(TALISMAN_URL)

  if soup:
    print("Page fetched successfully. Parsing table...")
    all_talisman_data = parse_talisman_table(soup, TABLE_SELECTOR)

    if all_talisman_data:
      print(f"\nSuccessfully parsed {len(all_talisman_data)} talismans.")
      
      # Apply overrides from YAML file
      all_talisman_data = apply_overrides(all_talisman_data)
      
      # Save to file, overwriting the old one
      output_filename = "talismans.json"
      try:
        with open(output_filename, "w") as f:
          json.dump(all_talisman_data, f, indent=2)
        print(f"Data saved to {output_filename}")
      except IOError as e:
        print(f"Error writing to file {output_filename}: {e}")
    else:
      print("No talisman data was parsed. Check the script and website structure.")
  else:
    print("Failed to fetch the page. Cannot parse.")