import json
import time
from flask import Flask, request, jsonify, render_template, send_from_directory
from optimize_armor_build import optimize_build, load_json, ARMOR_DATA_FILE, DECORATIONS_FILE, TALISMANS_FILE

app = Flask(__name__)

# --- Load Data Globally (or cache it) ---
# Consider caching this data to avoid reloading on every request
try:
  armor_data = load_json(ARMOR_DATA_FILE)
  decorations_data = load_json(DECORATIONS_FILE)
  talismans_data = load_json(TALISMANS_FILE)
  with open('skills_list.json', 'r') as f:
    skills_list_data = json.load(f)
except Exception as e:
  # Handle data loading errors during startup
  print(f"FATAL: Could not load essential data files: {e}")
  # Depending on deployment, might want to exit or log differently
  exit(1)

@app.route('/api/skills', methods=['GET'])
def get_skills():
  """Returns the list of all available skills and their max levels."""
  return jsonify(skills_list_data)

# --- Serve Frontend ---
@app.route('/')
def index():
  """Serves the main HTML page."""
  return render_template('index.html')

# Flask automatically serves files from the 'static' directory if it exists.
# No explicit route needed for /static/style.css or /static/script.js

@app.route('/api/optimize', methods=['POST'])
def optimize():
  """
  Accepts target skills via JSON payload and returns the optimal build.
  Payload format: {"skills": {"Skill Name": level, ...}}
  """
  target_skills = request.json.get('skills')

  if not isinstance(target_skills, dict):
    return jsonify({"error": "Invalid payload format. 'skills' must be a dictionary."}), 400

  if not target_skills:
    return jsonify({"error": "'skills' dictionary cannot be empty."}), 400

  # Basic validation for skill levels (optional but recommended)
  for skill, level in target_skills.items():
    if not isinstance(level, int) or level <= 0:
      return jsonify({"error": f"Invalid level '{level}' for skill '{skill}'. Level must be a positive integer."}), 400

  print(f"Received optimization request for skills: {target_skills}")
  start_time = time.time()

  try:
    # Pass the pre-loaded data to the optimizer
    optimal_build = optimize_build(armor_data, decorations_data, talismans_data, target_skills)
    end_time = time.time()
    print(f"Optimization completed in {end_time - start_time:.2f} seconds.")

    if optimal_build:
      # Add the original target skills to the response for context
      optimal_build['target_skills'] = target_skills
      return jsonify(optimal_build)
    else:
      # The optimizer function prints infeasibility messages, return a clear error
      return jsonify({"error": "No build found matching the specified skills. The combination might be impossible."}), 404

  except Exception as e:
    # Catch unexpected errors during optimization
    print(f"Error during optimization: {e}")
    # Log the full traceback here in a real application
    return jsonify({"error": "An unexpected error occurred during optimization."}), 500

if __name__ == '__main__':
  # For local development testing
  app.run(debug=True)