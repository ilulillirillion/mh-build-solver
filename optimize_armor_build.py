import json
from ortools.sat.python import cp_model
from collections import defaultdict
import time

# --- Configuration ---
ARMOR_DATA_FILE = "armor_data.json"
DECORATIONS_FILE = "decorations.json"
TALISMANS_FILE = "talismans.json"
SET_BONUSES_FILE = "set_bonuses.json"     # Added
GROUP_BONUSES_FILE = "group_bonuses.json" # Added

# Slot weights for optimization
SLOT_WEIGHTS = {1: 1, 2: 2, 3: 3, 4: 4} # Lvl 4 included just in case

# --- Load Data ---
def load_json(filename):
    try:
        with open(filename, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: Data file '{filename}' not found.")
        exit(1)
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from '{filename}'.")
        exit(1)

# --- Main Optimization Logic ---
def optimize_build(armor_pieces, decorations, talismans, set_bonuses, group_bonuses, target_skills): # Added bonus data args
    model = cp_model.CpModel()
    solver = cp_model.CpSolver()
    # solver.parameters.log_search_progress = True
    solver.parameters.num_search_workers = 8 # Use multiple cores if available

    print("Loading and preprocessing data...")

    # --- Data Preprocessing ---
    pieces_by_slot = defaultdict(list)
    for i, piece in enumerate(armor_pieces):
        slot_type = piece.get("type")
        if slot_type in ["Head", "Chest", "Arms", "Waist", "Legs"]:
            piece['id'] = f"armor_{i}" # Ensure ID exists
            pieces_by_slot[slot_type].append(piece)

    for i, deco in enumerate(decorations):
        deco['id'] = f"deco_{i}" # Ensure ID exists
    for i, talisman in enumerate(talismans):
         talisman['id'] = f"talisman_{i}" # Ensure ID exists

    # Check if all target skills exist in the loaded data
    available_skills = set()
    for piece in armor_pieces:
        for skill in piece.get("skills", []): available_skills.add(skill["name"])
    for deco in decorations:
        for skill in deco.get("skills", []): available_skills.add(skill["name"])
    for talisman in talismans:
        for skill in talisman.get("skills", []): available_skills.add(skill["name"])
    # Also consider skills granted by bonuses as available
    for bonus in set_bonuses:
        for effect in bonus.get("effects", []): available_skills.add(effect["granted_skill"])
    for bonus in group_bonuses:
        for effect in bonus.get("effects", []): available_skills.add(effect["granted_skill"])

    missing_skills = set(target_skills.keys()) - available_skills
    if missing_skills:
        print("\nError: The following target skills are completely unavailable in the loaded data (check armor, decos, talismans, AND bonus effects):")
        for skill in missing_skills: print(f"- {skill}")
        print("Build is impossible.")
        return None

    # Preprocess bonus data for easier lookup
    set_bonus_effects = {b['name']: b.get('effects', []) for b in set_bonuses}
    group_bonus_effects = {b['name']: b.get('effects', []) for b in group_bonuses}

    print("Creating model variables...")
    # --- Create Model Variables ---
    armor_vars = {p['id']: model.NewBoolVar(p['id']) for slot in pieces_by_slot for p in pieces_by_slot[slot]}
    talisman_vars = {t['id']: model.NewBoolVar(t['id']) for t in talismans}
    max_possible_deco_count = sum(target_skills.values()) # Rough upper bound
    deco_vars = {d['id']: model.NewIntVar(0, max_possible_deco_count, d['id']) for d in decorations}

    print("Adding model constraints...")
    # --- Constraints ---
    # 1. Exactly one piece per armor slot
    for slot_type, pieces in pieces_by_slot.items():
        model.AddExactlyOne(armor_vars[p['id']] for p in pieces)

    # 2. Exactly one talisman
    model.AddExactlyOne(talisman_vars[t['id']] for t in talismans)

    # 3. Skill requirements
    for skill_name, target_level in target_skills.items():
        skill_expr = []
        # Armor Direct Skills
        for piece_id, var in armor_vars.items():
            piece = next(p for slot_pieces in pieces_by_slot.values() for p in slot_pieces if p['id'] == piece_id)
            for skill_info in piece.get("skills", []):
                if skill_info["name"] == skill_name: skill_expr.append(var * skill_info["level"])
        # Talisman Direct Skills
        for talisman_id, var in talisman_vars.items():
            talisman = next(t for t in talismans if t['id'] == talisman_id)
            for skill_info in talisman.get("skills", []):
                if skill_info["name"] == skill_name: skill_expr.append(var * skill_info["points"])
        # Decoration Skills
        for deco_id, count_var in deco_vars.items():
            deco = next(d for d in decorations if d['id'] == deco_id)
            for skill_info in deco.get("skills", []):
                 if skill_info["name"] == skill_name: skill_expr.append(count_var * skill_info["points"])

        # --- Add Set Bonus Skill Contributions ---
        for bonus_name, effects in set_bonus_effects.items():
            # Count pieces contributing to this set bonus
            pieces_with_bonus = [p['id'] for slot_pieces in pieces_by_slot.values() for p in slot_pieces if bonus_name in p.get('set_bonuses_provided', [])]
            if not pieces_with_bonus: continue # Skip if no armor piece provides this bonus
            count_set_bonus = model.NewIntVar(0, 5, f"count_{bonus_name}")
            model.Add(count_set_bonus == sum(armor_vars[pid] for pid in pieces_with_bonus))

            # Check each activation tier for the bonus
            for effect in effects:
                pieces_req = effect['pieces_required']
                granted_skill = effect['granted_skill']
                granted_level = effect['granted_level']

                if granted_skill == skill_name:
                    # Indicator variable: Is this tier active?
                    is_active_var = model.NewBoolVar(f"active_{bonus_name}_{pieces_req}pc")
                    # Link indicator to piece count
                    model.Add(count_set_bonus >= pieces_req).OnlyEnforceIf(is_active_var)
                    model.Add(count_set_bonus < pieces_req).OnlyEnforceIf(is_active_var.Not())
                    # Add skill points if active
                    skill_expr.append(is_active_var * granted_level)

        # --- Add Group Bonus Skill Contributions ---
        for bonus_name, effects in group_bonus_effects.items():
             # Group bonuses usually have only one effect/tier (3 pieces)
             if not effects: continue
             effect = effects[0] # Assume first effect is the relevant one
             pieces_req = effect['pieces_required'] # Should be 3
             granted_skill = effect['granted_skill']
             granted_level = effect['granted_level']

             if granted_skill == skill_name:
                 pieces_with_bonus = [p['id'] for slot_pieces in pieces_by_slot.values() for p in slot_pieces if bonus_name in p.get('group_bonuses_provided', [])]
                 if not pieces_with_bonus: continue
                 count_group_bonus = model.NewIntVar(0, 5, f"count_{bonus_name}")
                 model.Add(count_group_bonus == sum(armor_vars[pid] for pid in pieces_with_bonus))

                 is_active_var = model.NewBoolVar(f"active_{bonus_name}_{pieces_req}pc")
                 model.Add(count_group_bonus >= pieces_req).OnlyEnforceIf(is_active_var)
                 model.Add(count_group_bonus < pieces_req).OnlyEnforceIf(is_active_var.Not())
                 skill_expr.append(is_active_var * granted_level)


        # Final constraint for the target skill level
        if skill_expr: model.Add(sum(skill_expr) >= target_level)
        elif target_level > 0:
             print(f"Warning: Target skill '{skill_name}' cannot be obtained from any source (direct or bonus). Build might be impossible.")
             model.Add(1 == 0) # Force infeasibility

    # 4. Decoration Slot Limits
    total_slots_l1 = sum(armor_vars[p['id']] * p['slots'].get('level_1', 0) for slot in pieces_by_slot for p in pieces_by_slot[slot])
    total_slots_l2 = sum(armor_vars[p['id']] * p['slots'].get('level_2', 0) for slot in pieces_by_slot for p in pieces_by_slot[slot])
    total_slots_l3 = sum(armor_vars[p['id']] * p['slots'].get('level_3', 0) for slot in pieces_by_slot for p in pieces_by_slot[slot])
    total_slots_l4 = sum(armor_vars[p['id']] * p['slots'].get('level_4', 0) for slot in pieces_by_slot for p in pieces_by_slot[slot])
    used_slots_l1 = sum(deco_vars[d['id']] for d in decorations if d['slot_level'] == 1)
    used_slots_l2 = sum(deco_vars[d['id']] for d in decorations if d['slot_level'] == 2)
    used_slots_l3 = sum(deco_vars[d['id']] for d in decorations if d['slot_level'] == 3)
    used_slots_l4 = sum(deco_vars[d['id']] for d in decorations if d['slot_level'] == 4)
    model.Add(used_slots_l1 + used_slots_l2 + used_slots_l3 + used_slots_l4 <= total_slots_l1 + total_slots_l2 + total_slots_l3 + total_slots_l4)
    model.Add(used_slots_l2 + used_slots_l3 + used_slots_l4 <= total_slots_l2 + total_slots_l3 + total_slots_l4)
    model.Add(used_slots_l3 + used_slots_l4 <= total_slots_l3 + total_slots_l4)
    model.Add(used_slots_l4 <= total_slots_l4)

    # --- NEW Objective Function ---
    # Priority: 1. Minimize Decorators Used -> 2. Maximize Weighted Slots -> 3. Maximize Defense

    # Term 1: Total Decorations Used (to be minimized, so use negative sign)
    total_decorations_used = sum(deco_vars.values())

    # Term 2: Total Weighted Slots from Armor
    total_weighted_armor_slots = sum(
        armor_vars[p['id']] * (
            p['slots'].get('level_1', 0) * SLOT_WEIGHTS[1] +
            p['slots'].get('level_2', 0) * SLOT_WEIGHTS[2] +
            p['slots'].get('level_3', 0) * SLOT_WEIGHTS[3] +
            p['slots'].get('level_4', 0) * SLOT_WEIGHTS[4]
        ) for slot in pieces_by_slot for p in pieces_by_slot[slot]
    )

    # Term 3: Total Defense
    total_defense = sum(armor_vars[p['id']] * p['defense'] for slot in pieces_by_slot for p in pieces_by_slot[slot])

    # Define large weights for prioritization
    # Estimate upper bounds
    max_possible_defense = sum(max(p['defense'] for p in pieces) for pieces in pieces_by_slot.values() if pieces)
    max_possible_weighted_slots = sum(max( p['slots'].get('level_1', 0) * SLOT_WEIGHTS[1] +
                                            p['slots'].get('level_2', 0) * SLOT_WEIGHTS[2] +
                                            p['slots'].get('level_3', 0) * SLOT_WEIGHTS[3] +
                                            p['slots'].get('level_4', 0) * SLOT_WEIGHTS[4]
                                         for p in pieces) for pieces in pieces_by_slot.values() if pieces)

    # Weights to enforce priority: Minimize Decos > Maximize Slots > Maximize Defense
    W_Defense = 1 # Lowest priority
    W_Slots = max_possible_defense + 1
    W_DecoPenalty = max_possible_weighted_slots * W_Slots + 1 # Largest weight for penalty

    # Maximize: (-DecoCount * W_DecoPenalty) + (WeightedSlots * W_Slots) + (Defense * W_Defense)
    model.Maximize(
        -total_decorations_used * W_DecoPenalty +
        total_weighted_armor_slots * W_Slots +
        total_defense * W_Defense
    )

    print("Solving the model with new objective...")
    start_time = time.time()
    status = solver.Solve(model)
    end_time = time.time()
    print(f"Solver finished in {end_time - start_time:.2f} seconds.")

    # --- Process Solution ---
    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        print("Optimal solution found!")
        solution = {}
        chosen_armor = []
        chosen_talisman = None
        used_decorations = []
        final_skills = defaultdict(int)
        final_slots = defaultdict(int)
        final_defense = 0

        for piece_id, var in armor_vars.items():
            if solver.Value(var) == 1:
                piece = next(p for slot_pieces in pieces_by_slot.values() for p in slot_pieces if p['id'] == piece_id)
                chosen_armor.append(piece)
                final_defense += piece['defense']
                for slot_level_str, count in piece['slots'].items():
                    final_slots[slot_level_str] += count
                # Skill contribution will be recalculated globally later

        for talisman_id, var in talisman_vars.items():
             if solver.Value(var) == 1:
                talisman = next(t for t in talismans if t['id'] == talisman_id)
                chosen_talisman = talisman # Store the actual chosen talisman object
                break # Found the chosen one

        for deco_id, count_var in deco_vars.items():
            count = solver.Value(count_var)
            if count > 0:
                deco = next(d for d in decorations if d['id'] == deco_id)
                used_decorations.append({"deco": deco, "count": count})

        solution['armor'] = chosen_armor
        solution['talisman'] = chosen_talisman
        solution['decorations'] = used_decorations
        solution['defense'] = final_defense
        # solution['skills'] = final_skills # Recalculate below
        solution['slots'] = final_slots
        solution['objective_value'] = solver.ObjectiveValue() # Raw objective score

        # Recalculate final skills based on chosen gear
        final_skills_display = defaultdict(int)
        for piece in chosen_armor:
             for skill_info in piece.get("skills", []): final_skills_display[skill_info["name"]] += skill_info["level"]
        if chosen_talisman:
             for skill_info in chosen_talisman.get("skills", []): final_skills_display[skill_info["name"]] += skill_info["points"]
        for item in used_decorations:
             for skill_info in item['deco'].get("skills", []): final_skills_display[skill_info["name"]] += skill_info["points"] * item['count']

        # Add skills from activated bonuses
        # Set Bonuses
        active_set_bonuses = defaultdict(int)
        for piece in chosen_armor:
            for bonus_name in piece.get('set_bonuses_provided', []):
                active_set_bonuses[bonus_name] += 1

        print("\nChecking Activated Set Bonuses:") # Debug
        for bonus_name, count in active_set_bonuses.items():
            if bonus_name in set_bonus_effects:
                print(f"- {bonus_name}: {count} pieces") # Debug
                for effect in set_bonus_effects[bonus_name]:
                    if count >= effect['pieces_required']:
                        print(f"  - Activating {effect['pieces_required']}pc effect: +{effect['granted_level']} {effect['granted_skill']}") # Debug
                        final_skills_display[effect['granted_skill']] += effect['granted_level']
                        # Assuming higher tiers grant *additional* levels or different skills.
                        # If higher tiers REPLACE lower tiers for the *same skill*, this logic might overcount.
                        # Example: If 2pc gives SkillA+1 and 4pc gives SkillA+2, this adds +1 and +2.
                        # If 4pc should *replace* 2pc, we'd need to only add the highest satisfied tier's effect.
                        # For now, assume additive, but this might need refinement based on game mechanics.


        # Group Bonuses
        active_group_bonuses = defaultdict(int)
        for piece in chosen_armor:
             for bonus_name in piece.get('group_bonuses_provided', []):
                 active_group_bonuses[bonus_name] += 1

        print("\nChecking Activated Group Bonuses:") # Debug
        for bonus_name, count in active_group_bonuses.items():
             if bonus_name in group_bonus_effects:
                 print(f"- {bonus_name}: {count} pieces") # Debug
                 # Group bonuses typically have one tier (3 pieces)
                 if not group_bonus_effects[bonus_name]: continue # Skip if no effects defined
                 effect = group_bonus_effects[bonus_name][0] # Assume first/only effect
                 if count >= effect['pieces_required']: # Should be 3
                      print(f"  - Activating {effect['pieces_required']}pc effect: +{effect['granted_level']} {effect['granted_skill']}") # Debug
                      final_skills_display[effect['granted_skill']] += effect['granted_level']


        solution['skills'] = final_skills_display


        # Calculate remaining weighted slots based on this solution's gear and decos
        total_weighted_gear_slots = sum(
             p['slots'].get('level_1', 0) * SLOT_WEIGHTS[1] +
             p['slots'].get('level_2', 0) * SLOT_WEIGHTS[2] +
             p['slots'].get('level_3', 0) * SLOT_WEIGHTS[3] +
             p['slots'].get('level_4', 0) * SLOT_WEIGHTS[4]
             for p in chosen_armor
        )
        total_weighted_deco_cost = sum(d['count'] * SLOT_WEIGHTS[d['deco']['slot_level']] for d in used_decorations)
        solution['remaining_weighted_slots'] = total_weighted_gear_slots - total_weighted_deco_cost

        return solution

    elif status == cp_model.INFEASIBLE:
        print("Model is infeasible. No combination satisfies all constraints.")
        return None
    else:
        print(f"Solver returned status: {solver.StatusName(status)}")
        return None

# --- Main Execution ---
if __name__ == "__main__":
    armor_data = load_json(ARMOR_DATA_FILE)
    decorations_data = load_json(DECORATIONS_FILE)
    talismans_data = load_json(TALISMANS_FILE)
    set_bonuses_data = load_json(SET_BONUSES_FILE)     # Added
    group_bonuses_data = load_json(GROUP_BONUSES_FILE) # Added

    # Run the optimization directly with the new objective
    # Define target skills here for testing if needed
    test_target_skills = {
        "Outdoorsman": 1,
        "Botanist": 4,
        "Geologist": 3,
        "Entomologist": 1,
        "Speed Eating": 3,
        "Free Meal": 3,
        "Intimidator": 3,
        "Forager's Luck": 1,
    }
    optimal_build = optimize_build(armor_data, decorations_data, talismans_data, set_bonuses_data, group_bonuses_data, test_target_skills) # Added bonus data args

    if optimal_build:
        print("\n--- Optimal Build Found ---")
        print(f"Total Defense: {optimal_build['defense']}")
        print("\nArmor Pieces:")
        for piece in optimal_build['armor']:
            print(f"- {piece['type']} : {piece['piece_name']} (Set: {piece['set_name']})")
            print(f"  Slots: L1:{piece['slots'].get('level_1',0)} L2:{piece['slots'].get('level_2',0)} L3:{piece['slots'].get('level_3',0)} L4:{piece['slots'].get('level_4',0)}")
            print(f"  Skills: {', '.join([s['name'] + ' +' + str(s['level']) for s in piece['skills']]) if piece['skills'] else 'None'}")

        print("\nTalisman:")
        if optimal_build['talisman']:
            t = optimal_build['talisman']
            print(f"- {t['name']}")
            print(f"  Skills: {', '.join([s['name'] + ' +' + str(s['points']) for s in t['skills']]) if t['skills'] else 'None'}")
        else:
            print("- None")

        print("\nDecorations Used:")
        if optimal_build['decorations']:
            for item in optimal_build['decorations']:
                print(f"- {item['count']}x {item['deco']['name']} (L{item['deco']['slot_level']})")
        else:
            print("- None")

        print("\nResulting Skills (Including Decos & Talisman):")
        for skill, level in sorted(optimal_build['skills'].items()):
             if level > 0:
                target = test_target_skills.get(skill, 0) # Use the test target skills here
                met_str = "MET" if level >= target else "BELOW"
                status = f"(Target: {target} - {met_str})" if target > 0 else ""
                print(f"- {skill}: {level} {status}")


        print(f"\nTotal Weighted Slot Value Remaining: {optimal_build['remaining_weighted_slots']}")
        # print(f"Raw Objective Value: {optimal_build['objective_value']}") # Less intuitive now

    else:
        print("\nNo optimal build found matching the criteria.")
