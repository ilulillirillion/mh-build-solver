import requests
import json
import re
import yaml
import os
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import time # Added for potential delays

# --- Constants ---
# Fextralife URLs and Selectors
FEXTRA_SKILL_URL = "https://monsterhunterwilds.wiki.fextralife.com/Skills"
FEXTRA_SKILL_TABLE_SELECTOR = "#wiki-content-block > div.tabcontent.\\31 -tab.tabcurrent > div.table-responsive > table"
FEXTRA_BASE_URL = "https://monsterhunterwilds.wiki.fextralife.com" # Needed for joining set bonus URLs

# Kiranico URLs
KIRANICO_SKILL_URL = "https://mhwilds.kiranico.com/data/skills"
KIRANICO_ARMOR_INDEX_URL = "https://mhwilds.kiranico.com/data/armor-series"
KIRANICO_BASE_URL = "https://mhwilds.kiranico.com"

# Files
OVERRIDE_FILE = "input_overrides.yml"
ARMOR_OUTPUT_FILE = "armor_data.json"
WEAPON_SKILLS_OUTPUT_FILE = "weapon_skills.json"
ARMOR_SKILLS_OUTPUT_FILE = "armor_skills.json"
SET_BONUSES_OUTPUT_FILE = "set_bonuses.json"
GROUP_BONUSES_OUTPUT_FILE = "group_bonuses.json"
OLD_SKILLS_LIST_FILE = "skills_list.json"


# --- Helper Functions ---
def fetch_soup(url):
  """Fetches URL and returns BeautifulSoup object."""
  headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
  }
  try:
    print(f"Fetching: {url}")
    time.sleep(0.5) # Be polite
    response = requests.get(url, headers=headers, timeout=20)
    response.raise_for_status()
    # print("Fetch successful.") # Reduce verbosity
    return BeautifulSoup(response.text, 'html.parser')
  except requests.exceptions.RequestException as e:
    print(f"Error fetching {url}: {e}")
    return None

# --- Skill Scraping Functions ---
def parse_skill_table(soup, selector):
  """
  Parses the main Fextralife skill table.
  Extracts basic info, parses Group Skill effects directly, collects Set Bonus URLs.
  Returns: tuple(list_of_all_skill_dicts, dict_of_set_bonus_urls)
  """
  skill_data = []
  set_bonus_urls = {} # Store name -> URL for set bonuses only
  table = soup.select_one(selector)

  if not table:
    print(f"Error: Could not find the skill table with selector '{selector}'")
    return None, None

  tbody = table.find('tbody')
  if not tbody:
      print("Error: Could not find tbody within the skill table.")
      return None, None

  rows = tbody.find_all('tr')
  print(f"Found {len(rows)} rows in the Fextralife skill table.")

  for row in rows:
    cols = row.find_all('td')
    if len(cols) < 5: continue

    try:
      # Name (Col 0)
      name_cell = cols[0]
      name_link = name_cell.find('a')
      skill_name = name_link.get_text(strip=True) if name_link else name_cell.get_text(strip=True)
      skill_name = skill_name.replace('\n', ' ').strip()
      skill_url = urljoin(FEXTRA_BASE_URL, name_link['href']) if name_link and name_link.has_attr('href') else None

      if not skill_name or skill_name.lower() == 'name': continue

      # Fextra Type (Col 1)
      fextra_type_cell = cols[1]
      fextra_type_raw = fextra_type_cell.get_text(strip=True)
      fextra_type_lower = fextra_type_raw.lower()

      # Max Level (Col 4)
      level_cell = cols[4]
      level_text = level_cell.get_text(strip=True)
      level_match = re.search(r'(\d+)\s+level', level_text, re.IGNORECASE)
      max_level = int(level_match.group(1)) if level_match else 0
      if max_level == 0:
          # Don't warn for bonuses as their level isn't standard
          if "bonus" not in fextra_type_lower and "group" not in fextra_type_lower:
              print(f"Warning: Could not parse max level for '{skill_name}'. Found text: '{level_text}'. Setting level to 0.")

      skill_entry = {
        "name": skill_name,
        "max_level": max_level,
        "fextra_type": fextra_type_raw # Keep for categorization step
      }

      # Handle Group/Set Bonuses specifically
      if "group skill" in fextra_type_lower:
          effect = None
          if len(cols) > 3:
              progression_cell = cols[3]
              # Extract skill name from "3 Pieces Unlock: Skill Name"
              match = re.search(r'3\s+Pieces(?: Unlock)?:?\s*(.*)', progression_cell.get_text(strip=True), re.IGNORECASE)
              if match:
                  granted_skill_name_raw = match.group(1).strip().split('.')[0].split(',')[0].strip()
                  # Attempt to find link for the granted skill to get clean name
                  granted_skill_link = progression_cell.find('a', string=re.compile(r'\s*' + re.escape(granted_skill_name_raw) + r'\s*', re.IGNORECASE))
                  granted_skill_name = granted_skill_link.get_text(strip=True) if granted_skill_link else granted_skill_name_raw

                  if granted_skill_name and len(granted_skill_name) < 50: # Basic validation
                       effect = {"pieces_required": 3, "granted_skill": granted_skill_name, "granted_level": 1}
                  else:
                       print(f"    Warning: Could not parse granted skill name from '{progression_cell.get_text(strip=True)}' for group bonus '{skill_name}'")

          if effect:
              skill_entry["effects"] = [effect] # Store as list for consistency
          else:
               print(f"  Warning: Could not parse effect for group bonus '{skill_name}'.")
          skill_data.append(skill_entry)

      elif "set bonus skill" in fextra_type_lower:
          if skill_url:
              set_bonus_urls[skill_name] = skill_url
          # Add basic entry; effects added later after fetching individual page
          skill_data.append(skill_entry)
      else:
          # Regular skill or decoration skill
          skill_data.append(skill_entry)

    except Exception as e:
      print(f"Error processing Fextra skill row for '{skill_name if 'skill_name' in locals() else 'UNKNOWN'}': {e}")
      # print(f"Row content: {row}") # Can be verbose
      continue

  return skill_data, set_bonus_urls


def fetch_kiranico_skill_types(url=KIRANICO_SKILL_URL):
    """
    Fetches skill names from Kiranico to map Fextralife 'Decoration Skill'
    into 'weapon_skills' or 'armor_skills'.
    Returns a dictionary mapping skill name to 'weapon_skills' or 'armor_skills'.
    """
    print(f"Fetching decoration skill types map from Kiranico: {url}")
    soup = fetch_soup(url)
    if not soup:
        print("Error: Failed to fetch Kiranico page. Cannot differentiate decoration skills.")
        return None

    deco_skill_map = {}
    categories = soup.find_all('h3')
    if not categories:
        print("Error: Could not find category headers (h3) on Kiranico page.")
        return None

    # print(f"Found {len(categories)} categories on Kiranico for deco check.") # Less verbose
    for category_tag in categories:
        category_name = category_tag.get_text(strip=True)
        kiranico_type_key = None
        if category_name == "Weapon":
            kiranico_type_key = "weapon_skills"
        elif category_name == "Equip":
            kiranico_type_key = "armor_skills"
        else: continue # Only care about Weapon/Equip

        skill_container = category_tag.find_next_sibling('div')
        skill_links = []
        if skill_container: skill_links = skill_container.find_all('a')
        else: skill_links = category_tag.find_all_next('a', limit=50)

        if not skill_links: continue

        for link in skill_links:
            skill_name = link.get_text(strip=True)
            normalized_name = skill_name.replace('/', '-')
            if normalized_name and normalized_name not in deco_skill_map:
                 deco_skill_map[normalized_name] = kiranico_type_key

    print(f"Successfully mapped {len(deco_skill_map)} skills from Kiranico for decoration check.")
    return deco_skill_map

def parse_fextra_set_bonus_page(url):
    """
    Parses an individual Fextralife set bonus page (infobox table)
    to extract the skills granted at 2 and 4 pieces.
    Uses FIXED piece requirements (2, 4).
    Returns: list of effect dicts or None if parsing fails.
    """
    # print(f"  Fetching set bonus page: {url}") # Reduce verbosity
    soup = fetch_soup(url)
    if not soup:
        print(f"    Warning: Failed to fetch set bonus page: {url}")
        return None

    infobox_table = soup.select_one("#infobox > div > table")
    if not infobox_table:
        # Try finding table without assuming infobox structure as fallback
        infobox_table = soup.find('table', class_='wiki_table')
        if not infobox_table:
             print(f"    Warning: Could not find infobox table on set bonus page: {url}")
             return None

    effects = []
    rows = infobox_table.find_all('tr')
    skill_map = {} # To store skill name found for 2pc and 4pc

    for row in rows:
        cols = row.find_all('td')
        if len(cols) == 2:
            requirement_text = cols[0].get_text(strip=True).lower()
            skill_cell = cols[1]
            skill_link = skill_cell.find('a')
            granted_skill_name = skill_link.get_text(strip=True) if skill_link else None

            if not granted_skill_name:
                continue

            # Determine level from name (e.g., "Skill Name II")
            level = 1
            roman_match = re.search(r'\s+(V|IV|III|II|I)$', granted_skill_name)
            if roman_match:
                roman = roman_match.group(1)
                if roman == 'V': level = 5
                elif roman == 'IV': level = 4
                elif roman == 'III': level = 3
                elif roman == 'II': level = 2
                elif roman == 'I': level = 1
            # Remove Roman numeral suffix if present
            base_skill_name = re.sub(r'\s+(V|IV|III|II|I)$', '', granted_skill_name).strip()


            if "2 piece" in requirement_text:
                 skill_map[2] = {"skill": base_skill_name, "level": level}
            elif "4 piece" in requirement_text:
                 skill_map[4] = {"skill": base_skill_name, "level": level}

    # Construct final effects list using fixed piece counts
    if 2 in skill_map:
        effects.append({
            "pieces_required": 2,
            "granted_skill": skill_map[2]["skill"],
            "granted_level": skill_map[2]["level"]
        })
    if 4 in skill_map:
         effects.append({
            "pieces_required": 4,
            "granted_skill": skill_map[4]["skill"],
            "granted_level": skill_map[4]["level"]
        })

    if effects:
        # print(f"    Parsed effects: {effects}") # Reduce verbosity
        return effects
    else:
        print(f"    Warning: Could not parse any effects from infobox table for {url}")
        return None


def apply_skill_overrides(skill_data, category_key, override_file=OVERRIDE_FILE):
  """Applies overrides for a specific category from YAML file to the skill data."""
  try:
    with open(override_file, 'r') as f:
      all_overrides = yaml.safe_load(f)

    if not all_overrides or category_key not in all_overrides or not all_overrides[category_key]:
      return skill_data

    category_overrides = all_overrides[category_key]
    if not category_overrides: return skill_data

    skill_dict = {s['name']: s for s in skill_data}
    override_count = 0
    added_count = 0
    for override in category_overrides:
      is_bonus = category_key in ["set_bonuses", "group_bonuses"]
      # Check format - bonuses might have 'effects' instead of 'max_level' in overrides
      valid_format = isinstance(override, dict) and 'name' in override and \
                     ('max_level' in override or (is_bonus and 'effects' in override))

      if not valid_format:
          print(f"Warning: Skipping invalid override format in '{category_key}': {override}")
          continue

      name = override['name']
      # Ensure max_level exists even if only effects are provided for bonuses in override
      if is_bonus and 'max_level' not in override:
          override['max_level'] = skill_dict.get(name, {}).get('max_level', 1) # Default or keep original

      if name in skill_dict:
        print(f"Applying override for existing skill in '{category_key}': {name}")
        skill_dict[name] = override
        override_count += 1
      else:
        print(f"Adding new skill from override to '{category_key}': {name}")
        skill_dict[name] = override
        added_count += 1

    if override_count > 0 or added_count > 0:
        print(f"Applied {override_count} overrides and added {added_count} new skills for category '{category_key}' from {override_file}")

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

# --- Armor Scraping Functions ---
def get_armor_set_urls(index_url):
  """Gets all individual armor set page URLs from the Kiranico index page."""
  print(f"\nFetching armor set URLs from Kiranico index: {index_url}")
  soup = fetch_soup(index_url)
  if not soup: return []

  urls = set()
  for link in soup.find_all('a', href=True):
    href = link['href']
    if href.startswith('/data/armor-series/') and href != '/data/armor-series':
        full_url = urljoin(KIRANICO_BASE_URL, href)
        urls.add(full_url)

  print(f"Found {len(urls)} armor set URLs.")
  return list(urls)

def parse_armor_page(url, set_bonus_names, group_bonus_names):
  """Parses an individual Kiranico armor set page and extracts piece data, identifying bonuses."""
  soup = fetch_soup(url)
  if not soup: return []

  armor_pieces_data = []
  set_name_tag = soup.find('h2')
  set_name = set_name_tag.get_text(strip=True) if set_name_tag else "Unknown Set"
  # print(f"Parsing armor set: {set_name} ({url})") # Reduce verbosity

  tables = soup.select('div.my-8 div.relative > table')
  if len(tables) < 3:
      print(f"  Warning: Expected at least 3 tables for {set_name}, found {len(tables)}. Skipping set.")
      return []

  stats_table = tables[1]
  skills_table = tables[2]

  stats_data = {}
  stats_rows = stats_table.find('tbody').find_all('tr')
  if not stats_rows or not stats_rows[0].find('th'):
      # print(f"  Warning: Stats table header not found for {set_name}. Skipping.") # Reduce verbosity
      return []

  for row in stats_rows[1:]: # Skip header
    cols = row.find_all(['td', 'th'])
    if len(cols) < 8: continue
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

  skills_rows = skills_table.find('tbody').find_all('tr')
  if not skills_rows or not skills_rows[0].find('th'):
      # print(f"  Warning: Skills table header not found for {set_name}. Skipping.") # Reduce verbosity
      return []

  for row in skills_rows[1:]: # Skip header
    cols = row.find_all(['td', 'th'])
    if len(cols) < 4: continue
    piece_name = cols[1].get_text(strip=True)
    slots_text = cols[2].get_text(strip=True)
    skills_tags = cols[3].find_all('a')

    slots = {
        "level_1": slots_text.count('[1]'), "level_2": slots_text.count('[2]'),
        "level_3": slots_text.count('[3]'), "level_4": slots_text.count('[4]'),
    }
    skills = []
    set_bonuses_provided = []
    group_bonuses_provided = []
    for skill_tag in skills_tags:
        skill_text = skill_tag.get_text(strip=True)
        skill_name_part = skill_text.split('+')[0].strip()
        if skill_name_part in set_bonus_names:
            if skill_name_part not in set_bonuses_provided: set_bonuses_provided.append(skill_name_part)
        elif skill_name_part in group_bonus_names:
            if skill_name_part not in group_bonuses_provided: group_bonuses_provided.append(skill_name_part)
        else:
            skill_level = int(skill_text.split('+')[1]) if '+' in skill_text else 1
            skills.append({"name": skill_name_part, "level": skill_level})

    if piece_name in stats_data:
        armor_piece = {
            "set_name": set_name, "piece_name": piece_name,
            **stats_data[piece_name],
            "slots": slots, "skills": skills,
            "set_bonuses_provided": sorted(list(set(set_bonuses_provided))),
            "group_bonuses_provided": sorted(list(set(group_bonuses_provided)))
        }
        armor_pieces_data.append(armor_piece)
    # else: # Reduce verbosity
        # print(f"  Warning: Mismatch finding stats for piece '{piece_name}' in set '{set_name}'")

  return armor_pieces_data


# --- Main Execution ---
if __name__ == "__main__":
    print("--- Starting Combined Data Scraping ---")

    # == Part 1: Skill Scraping & Categorization ==
    print("\n--- Phase 1: Processing Skills ---")
    # 1a. Fetch main skill table from Fextralife
    print(f"Fetching skill data from Fextralife: {FEXTRA_SKILL_URL}")
    fextra_soup = fetch_soup(FEXTRA_SKILL_URL)
    if not fextra_soup: exit(1)
    print("Parsing Fextralife skill table...")
    # Gets skill list (incl. group bonus effects) and set bonus URLs
    fextra_skills, set_bonus_urls = parse_skill_table(fextra_soup, FEXTRA_SKILL_TABLE_SELECTOR)
    if fextra_skills is None: exit(1)
    print(f"Successfully parsed {len(fextra_skills)} skills from Fextralife main table.")
    print(f"Identified {len(set_bonus_urls)} potential set bonus skills to fetch effects for.")

    # 1b. Fetch Kiranico map for deco skill check
    kiranico_deco_check_map = fetch_kiranico_skill_types()

    # 1c. Fetch effects for Set Bonuses from their individual pages
    print("\nFetching effects for Set Bonus skills...")
    set_bonus_effects_map = {}
    for name, url in set_bonus_urls.items():
        effects = parse_fextra_set_bonus_page(url)
        if effects:
            set_bonus_effects_map[name] = effects

    # 1d. Categorize skills and add effects
    print("\nCategorizing skills and adding effects...")
    categorized_skills = {
      "weapon_skills": [], "armor_skills": [],
      "set_bonuses": [], "group_bonuses": []
    }
    deco_skill_check_count = 0
    for skill in fextra_skills:
        skill_name = skill['name']
        fextra_type = skill.get('fextra_type', '').lower()
        # Base entry only includes name and max_level for weapon/armor skills
        skill_entry_base = {"name": skill_name, "max_level": skill['max_level']}

        if "weapon skill" in fextra_type:
            categorized_skills["weapon_skills"].append(skill_entry_base)
        elif "armor skill" in fextra_type:
            categorized_skills["armor_skills"].append(skill_entry_base)
        elif "set bonus skill" in fextra_type:
            # Add effects scraped from individual page
            bonus_entry = {"name": skill_name, "max_level": skill['max_level']}
            if skill_name in set_bonus_effects_map:
                 bonus_entry["effects"] = set_bonus_effects_map[skill_name]
            else:
                 print(f"  Warning: No effects found/parsed for set bonus '{skill_name}' from its page.")
            categorized_skills["set_bonuses"].append(bonus_entry)
        elif "group skill" in fextra_type:
             # Add effects parsed directly from main table (if present in skill dict)
            bonus_entry = {"name": skill_name, "max_level": skill['max_level']}
            if "effects" in skill: # Effects were added during parse_skill_table
                 bonus_entry["effects"] = skill["effects"]
            # No warning here if effects missing, already warned in parse_skill_table
            categorized_skills["group_bonuses"].append(bonus_entry)
        elif "decoration skill" in fextra_type:
            deco_skill_check_count += 1
            normalized_name = skill_name.replace('/', '-')
            kiranico_category = kiranico_deco_check_map.get(normalized_name) if kiranico_deco_check_map else None
            if kiranico_category == "weapon_skills":
                categorized_skills["weapon_skills"].append(skill_entry_base)
            else: # Default deco skills to armor if not weapon or not found
                categorized_skills["armor_skills"].append(skill_entry_base)
                if not kiranico_category: print(f"  Info: Defaulted '{skill_name}' (Decoration Skill) to Armor Skill (not found on Kiranico map).")
                elif kiranico_category != "armor_skills": print(f"  Info: Defaulted '{skill_name}' (Decoration Skill) to Armor Skill (unexpected Kiranico type: {kiranico_category}).")
        else:
            print(f"  Warning: Unknown Fextralife type '{skill.get('fextra_type', '')}' for skill '{skill_name}'. Defaulting to Armor Skill.")
            categorized_skills["armor_skills"].append(skill_entry_base)

    print(f"\nCategorization complete:")
    print(f"- Checked {deco_skill_check_count} skills listed as 'Decoration Skill'.")
    for key, skills_list in categorized_skills.items(): print(f"- {key}: {len(skills_list)}")

    # 1e. Apply overrides per skill category FIRST
    print("\nApplying skill overrides...")
    for category_key, skills_list in categorized_skills.items():
        categorized_skills[category_key] = apply_skill_overrides(skills_list, category_key)

    # 1f. Create sets of bonus names AFTER categorization and overrides
    print("\nCreating bonus name sets for armor lookup...")
    set_bonus_names = {s['name'] for s in categorized_skills['set_bonuses']}
    group_bonus_names = {s['name'] for s in categorized_skills['group_bonuses']}
    print(f"Created set with {len(set_bonus_names)} set bonus names.")
    print(f"Created set with {len(group_bonus_names)} group bonus names.")

    # 1g. Save categorized skill files
    print("\nSaving categorized skill files...")
    for category_key, data_list in categorized_skills.items():
        filename = f"{category_key}.json"
        data_list.sort(key=lambda x: x['name'])
        try:
            with open(filename, "w") as f:
                f.write("[\n")
                for i, skill in enumerate(data_list):
                    f.write(f"  {json.dumps(skill)}")
                    f.write(",\n" if i < len(data_list) - 1 else "\n")
                f.write("]\n")
            print(f"Data saved to {filename}")
        except IOError as e: print(f"Error writing to file {filename}: {e}")

    # == Part 2: Armor Scraping ==
    print("\n--- Phase 2: Processing Armor ---")
    all_armor_data = []
    armor_set_urls = get_armor_set_urls(KIRANICO_ARMOR_INDEX_URL)

    print(f"\nParsing {len(armor_set_urls)} armor set pages...")
    for url in armor_set_urls:
        # Pass the bonus name sets to the armor parser
        set_data = parse_armor_page(url, set_bonus_names, group_bonus_names)
        if set_data:
            all_armor_data.extend(set_data)

    # TODO: Implement apply_armor_overrides if needed, similar to skills
    # print("\nApplying armor overrides...")
    # all_armor_data = apply_armor_overrides(all_armor_data)

    # Save armor data
    print(f"\nSaving armor data ({len(all_armor_data)} pieces)...")
    try:
        with open(ARMOR_OUTPUT_FILE, "w") as f:
            json.dump(all_armor_data, f, indent=2)
        print(f"Data saved to {ARMOR_OUTPUT_FILE}")
    except IOError as e:
        print(f"Error writing to file {ARMOR_OUTPUT_FILE}: {e}")

    # == Part 3: Cleanup ==
    print("\n--- Phase 3: Cleanup ---")
    if os.path.exists(OLD_SKILLS_LIST_FILE):
        try:
            os.remove(OLD_SKILLS_LIST_FILE)
            print(f"Removed old {OLD_SKILLS_LIST_FILE}")
        except OSError as e:
            print(f"Error removing {OLD_SKILLS_LIST_FILE}: {e}")

    print("\n--- Combined Data Scraping Finished ---")
