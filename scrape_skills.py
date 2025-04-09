import requests
import json
import re
import yaml
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# Fextralife URL and Selector
FEXTRA_SKILL_URL = "https://monsterhunterwilds.wiki.fextralife.com/Skills"
FEXTRA_TABLE_SELECTOR = "#wiki-content-block > div.tabcontent.\\31 -tab.tabcurrent > div.table-responsive > table"

# Kiranico URL
KIRANICO_SKILL_URL = "https://mhwilds.kiranico.com/data/skills"

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

      # --- Extract Fextralife Type (Column 1) ---
      fextra_type_cell = cols[1]
      fextra_type_raw = fextra_type_cell.get_text(strip=True)

      skill_data.append({
        "name": skill_name,
        "max_level": max_level,
        "fextra_type": fextra_type_raw # Store Fextralife type
      })

    except Exception as e:
      print(f"Error processing row for skill '{skill_name if 'skill_name' in locals() else 'UNKNOWN'}': {e}")
      print(f"Row content: {row}")
      continue # Skip row on error

  return skill_data

def apply_skill_overrides(skill_data, category_key, override_file=OVERRIDE_FILE):
  """Applies overrides for a specific category from YAML file to the skill data."""
  try:
    with open(override_file, 'r') as f:
      all_overrides = yaml.safe_load(f)

    if not all_overrides or category_key not in all_overrides or not all_overrides[category_key]:
      print(f"No overrides found for category '{category_key}' in {override_file}")
      return skill_data

    category_overrides = all_overrides[category_key]

    # Create a dictionary of skills by name for easier lookup
    skill_dict = {s['name']: s for s in skill_data}

    # Apply overrides
    override_count = 0
    added_count = 0
    for override in category_overrides:
      if not isinstance(override, dict) or 'name' not in override or 'max_level' not in override:
          print(f"Warning: Skipping invalid override format in '{category_key}': {override}")
          continue

      name = override['name']
      if name in skill_dict:
        # Replace existing skill
        print(f"Applying override for existing skill in '{category_key}': {name}")
        skill_dict[name] = override # Assumes override has 'name' and 'max_level'
        override_count += 1
      else:
        # Add new skill if it doesn't exist in the scraped data for this category
        print(f"Adding new skill from override to '{category_key}': {name}")
        skill_dict[name] = override
        added_count += 1

    print(f"Applied {override_count} overrides and added {added_count} new skills for category '{category_key}' from {override_file}")

    # Convert dictionary back to list
    return list(skill_dict.values())

  except FileNotFoundError:
    print(f"Override file {override_file} not found. Continuing without overrides.")
    return skill_data
  except yaml.YAMLError as e:
    print(f"Error parsing YAML in {override_file}: {e}")
    return skill_data
  except Exception as e:
    print(f"Unexpected error applying overrides for '{category_key}': {e}")
    return skill_data


def fetch_kiranico_skill_types(url=KIRANICO_SKILL_URL):
    """Fetches skill names and types from Kiranico."""
    print(f"Fetching skill types from Kiranico: {url}")
    soup = fetch_soup(url)
    if not soup:
        print("Error: Failed to fetch Kiranico page. Cannot determine skill types.")
        return None

    skill_types = {}
    # Kiranico uses h3 for categories and then lists skills as links
    categories = soup.find_all('h3')
    if not categories:
        print("Error: Could not find category headers (h3) on Kiranico page.")
        return None

    print(f"Found {len(categories)} categories on Kiranico.")
    for category_tag in categories:
        category_name = category_tag.get_text(strip=True)
        kiranico_type_key = None # This will be the key for the overrides YAML
        if category_name == "Weapon":
            kiranico_type_key = "weapon_skills"
        elif category_name == "Equip":
            kiranico_type_key = "armor_skills" # Armor Skill
        elif category_name == "Group":
            kiranico_type_key = "group_bonuses" # Group Bonus
        elif category_name == "Series":
            kiranico_type_key = "set_bonuses" # Set Bonus
        else:
            print(f"Warning: Unknown Kiranico category '{category_name}'")
            continue

        # Skills are usually in the next sibling div containing links
        skill_container = category_tag.find_next_sibling('div')
        if not skill_container:
             # Sometimes structure might differ, try finding links directly after h3
             skill_links = category_tag.find_all_next('a', limit=50) # Limit search depth
        else:
             skill_links = skill_container.find_all('a')

        if not skill_links:
            print(f"Warning: No skill links found for Kiranico category '{category_name}'")
            continue

        for link in skill_links:
            skill_name = link.get_text(strip=True)
            # Basic normalization: handle cases like "Spread/Power Shots"
            normalized_name = skill_name.replace('/', '-')
            if normalized_name:
                if normalized_name in skill_types and skill_types[normalized_name] != kiranico_type_key:
                     print(f"Warning: Skill '{normalized_name}' found in multiple Kiranico categories ('{skill_types[normalized_name]}' and '{kiranico_type_key}'). Using first found.")
                elif normalized_name not in skill_types:
                    skill_types[normalized_name] = kiranico_type_key # Store the YAML key

    print(f"Successfully mapped {len(skill_types)} skills from Kiranico.")
    return skill_types


# --- Main Execution ---
if __name__ == "__main__":
  # 1. Fetch skills from Fextralife (Name, Max Level, Fextra Type)
  print(f"Fetching skill data from Fextralife: {FEXTRA_SKILL_URL}")
  fextra_soup = fetch_soup(FEXTRA_SKILL_URL)
  if not fextra_soup:
      print("Failed to fetch Fextralife page. Aborting.")
      exit(1)

  print("Fextralife page fetched successfully. Parsing table...")
  fextra_skills = parse_skill_table(fextra_soup, FEXTRA_TABLE_SELECTOR)
  if not fextra_skills:
      print("No skill data parsed from Fextralife. Check the script and website structure.")
      exit(1)
  print(f"Successfully parsed {len(fextra_skills)} skills from Fextralife.")

  # 2. Fetch Kiranico map ONLY for differentiating Decoration Skills
  # This map tells us if a skill found on Kiranico is 'weapon_skills' or 'armor_skills'
  kiranico_deco_check_map = fetch_kiranico_skill_types() # Keep original name, but use output carefully
  if kiranico_deco_check_map is None:
      print("Warning: Failed to fetch Kiranico skill types. Cannot reliably differentiate 'Decoration Skill' from Fextralife.")
      # Proceeding, but 'Decoration Skill' will default to armor_skills

  # 3. Categorize skills based PRIMARILY on Fextralife type
  categorized_skills = {
      "weapon_skills": [],
      "armor_skills": [],
      "set_bonuses": [],
      "group_bonuses": []
  }
  deco_skill_check_count = 0

  for skill in fextra_skills:
      skill_name = skill['name']
      fextra_type = skill.get('fextra_type', '').lower()
      # Prepare skill entry (without fextra_type)
      skill_entry = {"name": skill_name, "max_level": skill['max_level']}

      if "weapon skill" in fextra_type:
          categorized_skills["weapon_skills"].append(skill_entry)
      elif "armor skill" in fextra_type:
          categorized_skills["armor_skills"].append(skill_entry)
      elif "set bonus skill" in fextra_type:
          categorized_skills["set_bonuses"].append(skill_entry)
      elif "group skill" in fextra_type:
          categorized_skills["group_bonuses"].append(skill_entry)
      elif "decoration skill" in fextra_type:
          deco_skill_check_count += 1
          # ONLY use Kiranico map for "Decoration Skill" from Fextra
          normalized_name = skill_name.replace('/', '-')
          kiranico_category = kiranico_deco_check_map.get(normalized_name) if kiranico_deco_check_map else None

          if kiranico_category == "weapon_skills":
              print(f"Info: Categorized '{skill_name}' (Decoration Skill) as Weapon Skill based on Kiranico.")
              categorized_skills["weapon_skills"].append(skill_entry)
          else:
              if kiranico_category == "armor_skills":
                   print(f"Info: Categorized '{skill_name}' (Decoration Skill) as Armor Skill based on Kiranico.")
              elif kiranico_category: # Found on Kiranico but as Group/Set (unexpected for a deco skill)
                   print(f"Warning: '{skill_name}' (Decoration Skill) found as '{kiranico_category}' on Kiranico. Defaulting to Armor Skill.")
              else: # Not found on Kiranico
                   print(f"Warning: '{skill_name}' (Decoration Skill) not found on Kiranico map. Defaulting to Armor Skill.")
              categorized_skills["armor_skills"].append(skill_entry)
      else:
          # Handle any other unexpected Fextralife types
          print(f"Warning: Unknown Fextralife type '{skill.get('fextra_type', '')}' for skill '{skill_name}'. Defaulting to Armor Skill.")
          categorized_skills["armor_skills"].append(skill_entry)


  print(f"\nInitial categorization complete:")
  print(f"- Checked {deco_skill_check_count} skills listed as 'Decoration Skill' on Fextralife against Kiranico.")
  for key, skills_list in categorized_skills.items():
      print(f"- {key}: {len(skills_list)}")

  # 4. Apply overrides PER CATEGORY
  print("\nApplying overrides...")
  for category_key, skills_list in categorized_skills.items():
      # Ensure apply_skill_overrides uses the correct category_key from the dict
      categorized_skills[category_key] = apply_skill_overrides(skills_list, category_key)

  # 5. Save categorized and overridden skills to separate files
  print("\nSaving categorized skill files...")
  for category_key, data_list in categorized_skills.items():
      filename = f"{category_key}.json"
      # Sort data alphabetically by name before saving
      data_list.sort(key=lambda x: x['name'])
      try:
          with open(filename, "w") as f:
              # Use compact JSON format (one object per line)
              f.write("[\n")
              for i, skill in enumerate(data_list):
                  f.write(f"  {json.dumps(skill)}")
                  if i < len(data_list) - 1:
                      f.write(",\n")
                  else:
                      f.write("\n")
              f.write("]\n")
          print(f"Data saved to {filename}")
      except IOError as e:
          print(f"Error writing to file {filename}: {e}")

  # Remove the old combined file if it exists
  import os
  old_file = "skills_list.json"
  if os.path.exists(old_file):
      try:
          os.remove(old_file)
          print(f"\nRemoved old {old_file}")
      except OSError as e:
          print(f"Error removing {old_file}: {e}")