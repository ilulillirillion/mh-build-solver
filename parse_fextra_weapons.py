import csv
import json
import os
import re
from collections import defaultdict

# --- Constants ---
INPUT_DIR = "fextra_weapon_tables"
OUTPUT_FILE = "weapons_data.json"

# --- Helper Functions ---

def clean_name(raw_name):
    """Extracts the actual name from strings like 'hope bow i mhwilds wiki guide 200px Hope Bow I'"""
    # Remove common image/wiki text patterns
    cleaned = re.sub(r'^[a-z\s\d]+ wiki guide \d+px\s*', '', raw_name, flags=re.IGNORECASE).strip()
    # Fallback if the above didn't work, try taking text after the last known image extension
    if 'wiki guide' in cleaned.lower(): # Check if cleanup failed
         parts = re.split(r'\.(png|webp|jpg|jpeg|gif)', raw_name, flags=re.IGNORECASE)
         if len(parts) > 1:
             cleaned = parts[-1].strip() # Take the last part after an extension
         else: # Default to original if split fails
              cleaned = raw_name.strip()

    # Handle cases where name might be duplicated if no image text was present
    # e.g. "Weapon Name Weapon Name" -> "Weapon Name"
    words = cleaned.split()
    if len(words) > 1 and len(words) % 2 == 0:
        mid = len(words) // 2
        if words[:mid] == words[mid:]:
            cleaned = " ".join(words[:mid])

    return cleaned if cleaned else raw_name # Return original if cleaning results in empty string

def parse_fextra_slots(slot_str):
    """Parses Fextra slot icon text e.g., '2 slot... 1 slot...' into counts."""
    slots = {"level_1": 0, "level_2": 0, "level_3": 0, "level_4": 0}
    if not slot_str or slot_str == '-':
        return slots
    slots["level_4"] = len(re.findall(r'4 slot', slot_str, re.IGNORECASE))
    slots["level_3"] = len(re.findall(r'3 slot', slot_str, re.IGNORECASE))
    slots["level_2"] = len(re.findall(r'2 slot', slot_str, re.IGNORECASE))
    slots["level_1"] = len(re.findall(r'1 slot', slot_str, re.IGNORECASE))
    return slots

def parse_fextra_element(element_str):
    """Parses Fextra element string e.g., 'water icon... Water 110' or '(fire icon... Fire 100)'"""
    element_type = None
    element_value = 0
    is_hidden = False

    if not element_str or element_str == '-':
        return None, 0, False

    # Check for hidden status (parentheses)
    if element_str.startswith('(') and element_str.endswith(')'):
        is_hidden = True
        element_str = element_str[1:-1] # Remove parentheses for further parsing

    # Extract value
    value_match = re.search(r'(\d+)', element_str)
    if value_match:
        element_value = int(value_match.group(1))

    # Extract type (case-insensitive)
    if 'fire' in element_str.lower(): element_type = 'Fire'
    elif 'water' in element_str.lower(): element_type = 'Water'
    elif 'thunder' in element_str.lower(): element_type = 'Thunder'
    elif 'ice' in element_str.lower(): element_type = 'Ice'
    elif 'dragon' in element_str.lower(): element_type = 'Dragon'
    elif 'poison' in element_str.lower(): element_type = 'Poison'
    elif 'paralysis' in element_str.lower(): element_type = 'Paralysis'
    elif 'sleep' in element_str.lower(): element_type = 'Sleep'
    elif 'blast' in element_str.lower(): element_type = 'Blast'

    # Only return type if value is non-zero
    if element_value == 0:
        element_type = None

    return element_type, element_value, is_hidden

def parse_fextra_skills(skill_str):
    """Parses Fextra skill string e.g., 'focus skill... Focus Lv 2 airborne skill... Airborne Lv1'"""
    skills = []
    if not skill_str or skill_str == '-':
        return skills
    # Find all skill patterns like 'Skill Name LvX'
    # Regex looks for text preceding ' Lv' followed by a digit
    matches = re.findall(r'([a-zA-Z\s\'-]+)\s+Lv(\d+)', skill_str)
    for match in matches:
        skill_name = match[0].strip()
        # Clean up potential leading icon text if needed (simple approach)
        skill_name = re.sub(r'^[a-z\s]+ skill.*guide \d+px\s*', '', skill_name, flags=re.IGNORECASE).strip()
        skill_level = int(match[1])
        skills.append({"name": skill_name, "level": skill_level})
    return skills

def parse_affinity(affinity_str):
    """Parses affinity percentage string."""
    if not affinity_str or affinity_str == '-':
        return 0
    match = re.search(r'([+-]?\d+)%', affinity_str)
    return int(match.group(1)) if match else 0

def parse_defense(defense_str):
    """Parses defense bonus string."""
    if not defense_str or defense_str == '-':
        return 0
    match = re.search(r'(\d+)', defense_str)
    return int(match.group(1)) if match else 0

def get_column_indices(header_row):
    """Creates a map from header name variations to column index."""
    indices = {}
    normalized_headers = [h.lower().strip() for h in header_row]
    for i, header in enumerate(normalized_headers):
        # Map common variations to standardized keys
        if 'name' in header: indices['name'] = i
        elif 'rare' in header: indices['rare'] = i
        elif 'attac' in header: indices['attack'] = i
        elif 'element' in header: indices['element'] = i
        elif 'affin' in header: indices['affinity'] = i
        elif 'defen' in header: indices['defense'] = i
        elif 'slot' in header: indices['slots'] = i
        elif 'skill' in header: indices['skills'] = i
        # Weapon specific
        elif 'phial' in header: indices['phial'] = i
        elif 'shelling' in header: # Check before 'level'
             if 'type' in header: indices['shelling_type'] = i
             elif 'lvl' in header or 'level' in header: indices['shelling_level'] = i
        elif 'note' in header: indices['notes'] = i
        elif 'echo' in header: indices['echo'] = i
        elif 'kinsect' in header: indices['kinsect_level'] = i
        elif 'coating' in header: indices['coatings'] = i
        elif 'ammo' in header:
             if 'special' in header: indices['special_ammo'] = i
             else: indices['ammo'] = i # General ammo column
        elif 'mods' in header: indices['mods'] = i
    return indices


# --- Main Parsing Logic ---
def parse_fextra_csvs(input_dir):
    """Parses all weapon CSV files from the Fextra dump directory."""
    all_weapons_data = []
    if not os.path.isdir(input_dir):
        print(f"Error: Input directory '{input_dir}' not found.")
        return []

    for filename in os.listdir(input_dir):
        if filename.lower().endswith('.csv'):
            filepath = os.path.join(input_dir, filename)
            weapon_type = os.path.splitext(filename)[0].replace('_', ' ').title()
            print(f"\nProcessing File: {filename} (Type: {weapon_type})")

            try:
                with open(filepath, 'r', encoding='utf-8-sig') as f: # Use utf-8-sig to handle potential BOM
                    reader = csv.reader(f)
                    header = next(reader) # Read header row
                    col_indices = get_column_indices(header)

                    # Verify mandatory columns exist
                    mandatory_keys = ['name', 'attack', 'element', 'affinity', 'slots', 'skills']
                    if not all(key in col_indices for key in mandatory_keys):
                         print(f"  Warning: Skipping file {filename}. Missing one or more mandatory columns in header: {header}")
                         continue

                    for row in reader:
                        try:
                            # Ensure row has enough columns based on max index needed
                            max_needed_index = max(col_indices.values())
                            if len(row) <= max_needed_index:
                                # print(f"    Skipping short row: {row}")
                                continue

                            # Extract mandatory fields
                            name = clean_name(row[col_indices['name']])
                            raw_attack = int(row[col_indices['attack']]) if row[col_indices['attack']].isdigit() else 0
                            affinity = parse_affinity(row[col_indices['affinity']])
                            element_type, element_value, element_hidden = parse_fextra_element(row[col_indices['element']])
                            slots = parse_fextra_slots(row[col_indices['slots']])
                            skills = parse_fextra_skills(row[col_indices['skills']])
                            defense = parse_defense(row[col_indices.get('defense', '')]) # Optional

                            weapon_data = {
                                "name": name,
                                "weapon_type": weapon_type,
                                "raw_damage": raw_attack,
                                "element_type": element_type,
                                "element_damage": element_value,
                                "element_hidden": element_hidden,
                                "affinity": affinity,
                                "defense_bonus": defense,
                                "decoration_slots": slots,
                                "innate_skills": skills
                            }

                            # Extract optional fields gracefully
                            if 'phial' in col_indices: weapon_data['phial_type'] = row[col_indices['phial']].strip() or None
                            if 'shelling_type' in col_indices: weapon_data['shelling_type'] = row[col_indices['shelling_type']].strip() or None
                            if 'shelling_level' in col_indices: weapon_data['shelling_level'] = row[col_indices['shelling_level']].strip() or None # Keep as string like 'Lv1' or number?
                            if 'notes' in col_indices: weapon_data['notes'] = row[col_indices['notes']].strip() or None # Needs parsing note icons
                            if 'echo' in col_indices: weapon_data['echo_bubble'] = row[col_indices['echo']].strip() or None
                            if 'kinsect_level' in col_indices: weapon_data['kinsect_level'] = row[col_indices['kinsect_level']].strip() or None
                            if 'coatings' in col_indices: weapon_data['coatings'] = [c.strip() for c in re.findall(r'([a-zA-Z-]+ Coating)', row[col_indices['coatings']]) ] # Extract coating names
                            if 'ammo' in col_indices: weapon_data['ammo_summary'] = row[col_indices['ammo']].strip() or None # Raw ammo string for now
                            if 'special_ammo' in col_indices: weapon_data['special_ammo'] = row[col_indices['special_ammo']].strip() or None
                            if 'mods' in col_indices: weapon_data['mods_summary'] = row[col_indices['mods']].strip() or None # Raw mods string

                            all_weapons_data.append(weapon_data)

                        except Exception as e:
                            print(f"    Error processing row in {filename}: {e}")
                            print(f"    Row data: {row}")
                            continue
            except Exception as e:
                print(f"  Error reading or processing file {filename}: {e}")

    return all_weapons_data

# --- Main Execution ---
if __name__ == "__main__":
    print("--- Starting Fextra Weapon CSV Parsing ---")
    weapon_data = parse_fextra_csvs(INPUT_DIR)

    if weapon_data:
        print(f"\nSuccessfully parsed data for {len(weapon_data)} weapons from {len(os.listdir(INPUT_DIR))} CSV files.")
        # Save to file
        try:
            with open(OUTPUT_FILE, "w") as f:
                json.dump(weapon_data, f, indent=2)
            print(f"Data saved to {OUTPUT_FILE}")
        except IOError as e:
            print(f"Error writing to file {OUTPUT_FILE}: {e}")
    else:
        print("No weapon data was parsed from the CSV files.")

    print("\n--- Fextra Weapon CSV Parsing Finished ---")