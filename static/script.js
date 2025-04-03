document.addEventListener('DOMContentLoaded', () => {
  const skillSearchInput = document.getElementById('skill-search');
  const skillDropdown = document.getElementById('skill-dropdown');
  const selectedSkillsList = document.getElementById('selected-skills-list');
  const optimizeButton = document.getElementById('optimize-button');
  const loadingIndicator = document.getElementById('loading-indicator');
  const resultsDiv = document.getElementById('build-results');
  const errorMessageDiv = document.getElementById('error-message');

  let allSkillsData = []; // To store { name: "Skill Name", level: 1, maxLevel: 5 }
  let selectedSkills = {}; // To store { "Skill Name": level }

  // --- Fetch Skills and Populate Dropdown ---
  fetch('/api/skills')
    .then(response => {
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      return response.json();
    })
    .then(skills => {
      allSkillsData = [];
      skills.forEach(skill => {
        for (let i = 1; i <= skill.max_level; i++) {
          allSkillsData.push({ name: skill.name, level: i, maxLevel: skill.max_level });
        }
      });
      // Initial population (optional, could wait for input)
      // populateDropdown('');
    })
    .catch(error => {
      console.error('Error fetching skills:', error);
      errorMessageDiv.textContent = 'Error loading skills list. Please try refreshing the page.';
      errorMessageDiv.style.display = 'block';
    });

  // --- Dropdown Filtering and Display ---
  function populateDropdown(filter) {
    skillDropdown.innerHTML = ''; // Clear previous options
    const filteredSkills = allSkillsData.filter(skill =>
      `${skill.name} ${skill.level}`.toLowerCase().includes(filter.toLowerCase())
    );

    if (filteredSkills.length === 0) {
      skillDropdown.innerHTML = '<div>No skills found</div>';
    } else {
      filteredSkills.forEach(skill => {
        const div = document.createElement('div');
        div.textContent = `${skill.name} ${skill.level}`;
        div.dataset.skillName = skill.name;
        div.dataset.skillLevel = skill.level;
        div.addEventListener('click', () => {
          addSkill(skill.name, skill.level);
          skillSearchInput.value = ''; // Clear search input
          skillDropdown.classList.remove('show'); // Hide dropdown
        });
        skillDropdown.appendChild(div);
      });
    }
    skillDropdown.classList.add('show');
  }

  skillSearchInput.addEventListener('input', () => {
    populateDropdown(skillSearchInput.value);
  });

  // Hide dropdown if clicked outside
  document.addEventListener('click', (event) => {
    if (!skillSearchInput.contains(event.target) && !skillDropdown.contains(event.target)) {
      skillDropdown.classList.remove('show');
    }
  });

  // --- Manage Selected Skills ---
  function addSkill(name, level) {
    // Use the highest level if the same skill is added multiple times
    if (!selectedSkills[name] || level > selectedSkills[name]) {
        selectedSkills[name] = level;
    }
    renderSelectedSkills();
  }

  function removeSkill(name) {
    delete selectedSkills[name];
    renderSelectedSkills();
  }

  function renderSelectedSkills() {
    selectedSkillsList.innerHTML = ''; // Clear current list
    for (const name in selectedSkills) {
      const level = selectedSkills[name];
      const li = document.createElement('li');
      li.textContent = `${name} ${level}`;

      const removeButton = document.createElement('button');
      removeButton.textContent = 'X';
      removeButton.addEventListener('click', () => removeSkill(name));

      li.appendChild(removeButton);
      selectedSkillsList.appendChild(li);
    }
  }

  // --- Optimization Request ---
  optimizeButton.addEventListener('click', () => {
    if (Object.keys(selectedSkills).length === 0) {
      errorMessageDiv.textContent = 'Please select at least one skill.';
      errorMessageDiv.style.display = 'block';
      resultsDiv.innerHTML = ''; // Clear previous results
      return;
    }

    loadingIndicator.style.display = 'block';
    errorMessageDiv.style.display = 'none';
    resultsDiv.innerHTML = ''; // Clear previous results
    optimizeButton.disabled = true;

    fetch('/api/optimize', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ skills: selectedSkills }),
    })
    .then(response => {
        if (!response.ok) {
            // Try to parse error message from backend if available
            return response.json().then(err => { throw new Error(err.error || `HTTP error! status: ${response.status}`) });
        }
        return response.json();
    })
    .then(result => {
      displayResults(result);
    })
    .catch(error => {
      console.error('Error during optimization:', error);
      errorMessageDiv.textContent = `Optimization failed: ${error.message}`;
      errorMessageDiv.style.display = 'block';
    })
    .finally(() => {
      loadingIndicator.style.display = 'none';
      optimizeButton.disabled = false;
    });
  });

  // --- Display Results ---
  function displayResults(build) {
    resultsDiv.innerHTML = ''; // Clear previous results

    let htmlContent = `<h3>Optimal Build Found</h3>`;
    htmlContent += `<p><strong>Total Defense:</strong> ${build.defense}</p>`;

    htmlContent += `<h4>Armor Pieces:</h4><ul>`;
    build.armor.forEach(piece => {
      const skillsStr = piece.skills.length > 0
        ? piece.skills.map(s => `${s.name} +${s.level}`).join(', ')
        : 'None';
      // Fix: Access slots using object property access with default value 0
      const slots = piece.slots || {}; // Ensure slots object exists
      const slotsStr = `L1:${slots['level_1'] || 0} L2:${slots['level_2'] || 0} L3:${slots['level_3'] || 0} L4:${slots['level_4'] || 0}`;
      htmlContent += `<li><strong>${piece.type}:</strong> ${piece.piece_name} (Set: ${piece.set_name})<br/>&nbsp;&nbsp;Skills: ${skillsStr}<br/>&nbsp;&nbsp;Slots: ${slotsStr}</li>`;
    });
    htmlContent += `</ul>`;

    htmlContent += `<h4>Talisman:</h4>`;
    if (build.talisman) {
      const t = build.talisman;
      const skillsStr = t.skills.length > 0
        ? t.skills.map(s => `${s.name} +${s.points}`).join(', ')
        : 'None';
      htmlContent += `<p>${t.name}<br/>&nbsp;&nbsp;Skills: ${skillsStr}</p>`;
    } else {
      htmlContent += `<p>None</p>`;
    }

    htmlContent += `<h4>Decorations Used:</h4>`;
    if (build.decorations.length > 0) {
      htmlContent += `<ul>`;
      build.decorations.forEach(item => {
        htmlContent += `<li>${item.count}x ${item.deco.name} (L${item.deco.slot_level})</li>`;
      });
      htmlContent += `</ul>`;
    } else {
      htmlContent += `<p>None</p>`;
    }

    htmlContent += `<h4>Resulting Skills:</h4><ul>`;
    const finalSkills = build.skills || {}; // Use the skills from the response
    const targetSkills = build.target_skills || {}; // Use target skills from response
    for (const [skill, level] of Object.entries(finalSkills).sort()) {
         if (level > 0) {
            const target = targetSkills[skill] || 0;
            const met_str = level >= target ? "MET" : "BELOW";
            const status = target > 0 ? `(Target: ${target} - ${met_str})` : "";
            htmlContent += `<li>${skill}: ${level} ${status}</li>`;
         }
    }
    htmlContent += `</ul>`;

     htmlContent += `<p><strong>Total Weighted Slot Value Remaining:</strong> ${build.remaining_weighted_slots}</p>`;


    resultsDiv.innerHTML = htmlContent;
  }
});