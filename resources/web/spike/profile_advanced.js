// Profile tab -- "Advanced/Rules" group: RoutingRulesSection +
// SettingsProfilesSection (see routing_rules_section.py/
// settings_profiles_section.py). Both are fully live-apply -- every action
// hits the bridge/store directly, there's no batched "Enregistrer" button
// for this group.

const AR_FIELD_LABEL_KEYS = { name: "routing_rules.field_name", tracker: "routing_rules.field_tracker" };

function arSectionHeading(key) {
  const h = document.createElement("h3");
  h.className = "profile-section-heading";
  h.textContent = t(key);
  h.dataset.i18nKey = key;
  return h;
}

// ---------------------------------------------------------------- routing rules

let arRules = [];
let arEditingName = null; // non-null while the inline form is editing an existing rule

function arRuleRow(rule, index) {
  const row = document.createElement("div");
  row.className = "rule-row";

  const nameEl = document.createElement("span");
  nameEl.className = "rule-cell";
  nameEl.textContent = rule.name;
  nameEl.title = rule.name;
  row.appendChild(nameEl);

  const patternEl = document.createElement("span");
  patternEl.className = "rule-cell";
  patternEl.textContent = rule.pattern;
  patternEl.title = rule.pattern;
  row.appendChild(patternEl);

  const fieldEl = document.createElement("span");
  fieldEl.className = "rule-cell";
  fieldEl.textContent = AR_FIELD_LABEL_KEYS[rule.matchField] ? t(AR_FIELD_LABEL_KEYS[rule.matchField]) : rule.matchField;
  row.appendChild(fieldEl);

  const destEl = document.createElement("span");
  destEl.className = "rule-cell";
  destEl.textContent = rule.destination;
  destEl.title = rule.destination;
  row.appendChild(destEl);

  const actions = document.createElement("div");
  actions.className = "row-actions";

  const upBtn = document.createElement("button");
  upBtn.textContent = "▲";
  upBtn.disabled = index === 0;
  upBtn.addEventListener("click", () => arMoveRule(index, index - 1));
  actions.appendChild(upBtn);

  const downBtn = document.createElement("button");
  downBtn.textContent = "▼";
  downBtn.disabled = index === arRules.length - 1;
  downBtn.addEventListener("click", () => arMoveRule(index, index + 1));
  actions.appendChild(downBtn);

  const editBtn = document.createElement("button");
  editBtn.textContent = t("routing_rules.edit_button");
  editBtn.addEventListener("click", () => arOpenForm(rule));
  actions.appendChild(editBtn);

  const removeBtn = document.createElement("button");
  removeBtn.textContent = t("common.remove");
  removeBtn.addEventListener("click", () => arDeleteRule(rule.name));
  actions.appendChild(removeBtn);

  row.appendChild(actions);
  return row;
}

function arRenderRules() {
  const list = document.getElementById("arRulesList");
  list.replaceChildren();
  if (!arRules.length) {
    const note = document.createElement("p");
    note.className = "empty-note";
    note.textContent = t("web.profile_advanced.no_routing_rules");
    list.appendChild(note);
    return;
  }
  arRules.forEach((rule, index) => list.appendChild(arRuleRow(rule, index)));
}

function arReloadRules() {
  window.bridge.profileAdvanced.listRoutingRules((rules) => {
    arRules = rules;
    arRenderRules();
  });
}

function arMoveRule(from, to) {
  // Mutation is fire-and-forget (no result= on this slot, so nothing to
  // reject it) and the new order is already known locally -- updating
  // arRules directly and re-rendering avoids a round-trip re-fetch of the
  // same list this call just reordered.
  [arRules[from], arRules[to]] = [arRules[to], arRules[from]];
  window.bridge.profileAdvanced.reorderRoutingRules(arRules.map((r) => r.name));
  arRenderRules();
}

function arDeleteRule(name) {
  if (!confirm(t("routing_rules.delete_confirm_message", { name }))) return;
  window.bridge.profileAdvanced.deleteRoutingRule(name);
  arRules = arRules.filter((r) => r.name !== name);
  arRenderRules();
}

function arOpenForm(rule) {
  arEditingName = rule ? rule.name : null;
  document.getElementById("arFormTitle").textContent = rule ? t("routing_rules.dialog_edit_title") : t("routing_rules.dialog_add_title");
  document.getElementById("arNameInput").value = rule ? rule.name : "";
  document.getElementById("arPatternInput").value = rule ? rule.pattern : "";
  document.getElementById("arFieldSelect").value = rule ? rule.matchField : "name";
  document.getElementById("arDestInput").value = rule ? rule.destination : "";
  document.getElementById("arPostActionSelect").value = rule ? rule.postCompleteAction : "none";
  document.getElementById("arPostActionMoveToInput").value = rule ? rule.postCompleteMoveTo : "";
  document.getElementById("arPostActionSelect").dispatchEvent(new Event("change"));
  document.getElementById("arFormStatus").textContent = "";
  document.getElementById("arForm").style.display = "";
}

function arCloseForm() {
  document.getElementById("arForm").style.display = "none";
  arEditingName = null;
}

function arBuildRulesSection(container) {
  const section = document.createElement("div");
  section.className = "profile-section";
  section.appendChild(arSectionHeading("web.profile_advanced.routing_rules_heading"));

  const intro = document.createElement("p");
  intro.className = "field-note";
  intro.textContent = t("web.profile_advanced.routing_rules_intro");
  intro.dataset.i18nKey = "web.profile_advanced.routing_rules_intro";
  section.appendChild(intro);

  const header = document.createElement("div");
  header.className = "rule-row rule-header";
  [
    "routing_rules.column_name",
    "routing_rules.column_pattern",
    "routing_rules.column_field",
    "routing_rules.column_destination",
    null,
  ].forEach((key) => {
    const cell = document.createElement("span");
    if (key) {
      cell.textContent = t(key);
      cell.dataset.i18nKey = key;
    }
    header.appendChild(cell);
  });
  section.appendChild(header);

  const list = document.createElement("div");
  list.id = "arRulesList";
  list.className = "listbox";
  section.appendChild(list);

  const addBtnRow = document.createElement("div");
  addBtnRow.className = "field-row";
  const addBtn = document.createElement("button");
  addBtn.textContent = t("common.add");
  addBtn.dataset.i18nKey = "common.add";
  addBtn.addEventListener("click", () => arOpenForm(null));
  addBtnRow.appendChild(addBtn);
  section.appendChild(addBtnRow);

  // Inline add/edit form -- no native modal equivalent, just show/hide.
  const form = document.createElement("div");
  form.id = "arForm";
  form.className = "form-grid";
  form.style.display = "none";

  const formTitle = document.createElement("p");
  formTitle.id = "arFormTitle";
  formTitle.className = "field-label";
  form.appendChild(formTitle);

  const nameRow = document.createElement("div");
  nameRow.className = "field-row";
  const nameLabel = document.createElement("label");
  nameLabel.className = "field-label inline";
  nameLabel.textContent = t("routing_rules.name_label");
  nameLabel.dataset.i18nKey = "routing_rules.name_label";
  const nameInput = document.createElement("input");
  nameInput.type = "text";
  nameInput.id = "arNameInput";
  nameRow.appendChild(nameLabel);
  nameRow.appendChild(nameInput);
  form.appendChild(nameRow);

  const patternRow = document.createElement("div");
  patternRow.className = "field-row";
  const patternLabel = document.createElement("label");
  patternLabel.className = "field-label inline";
  patternLabel.textContent = t("routing_rules.pattern_label");
  patternLabel.dataset.i18nKey = "routing_rules.pattern_label";
  const patternInput = document.createElement("input");
  patternInput.type = "text";
  patternInput.id = "arPatternInput";
  patternRow.appendChild(patternLabel);
  patternRow.appendChild(patternInput);
  form.appendChild(patternRow);

  const fieldRow = document.createElement("div");
  fieldRow.className = "field-row";
  const fieldLabel = document.createElement("label");
  fieldLabel.className = "field-label inline";
  fieldLabel.textContent = t("routing_rules.field_label");
  fieldLabel.dataset.i18nKey = "routing_rules.field_label";
  const fieldSelect = document.createElement("select");
  fieldSelect.id = "arFieldSelect";
  Object.entries(AR_FIELD_LABEL_KEYS).forEach(([value, key]) => {
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = t(key);
    opt.dataset.i18nKey = key;
    fieldSelect.appendChild(opt);
  });
  fieldRow.appendChild(fieldLabel);
  fieldRow.appendChild(fieldSelect);
  form.appendChild(fieldRow);

  const destRow = document.createElement("div");
  destRow.className = "field-row";
  const destLabel = document.createElement("label");
  destLabel.className = "field-label inline";
  destLabel.textContent = t("routing_rules.destination_label");
  destLabel.dataset.i18nKey = "routing_rules.destination_label";
  const destInput = document.createElement("input");
  destInput.type = "text";
  destInput.id = "arDestInput";
  const destBrowseBtn = document.createElement("button");
  destBrowseBtn.textContent = t("common.browse");
  destBrowseBtn.dataset.i18nKey = "common.browse";
  destBrowseBtn.addEventListener("click", () => {
    window.bridge.dialogs.browseFolder(destInput.value, (path) => {
      if (path) destInput.value = path;
    });
  });
  destRow.appendChild(destLabel);
  destRow.appendChild(destInput);
  destRow.appendChild(destBrowseBtn);
  form.appendChild(destRow);

  // Post-completion action (catalogue idea): deliberately limited to move/
  // unzip, never an arbitrary command -- see routing_rules.RoutingRule.
  const actionRow = document.createElement("div");
  actionRow.className = "field-row";
  const actionLabel = document.createElement("label");
  actionLabel.className = "field-label inline";
  actionLabel.textContent = t("web.profile_advanced.post_action_label");
  actionLabel.dataset.i18nKey = "web.profile_advanced.post_action_label";
  const actionSelect = document.createElement("select");
  actionSelect.id = "arPostActionSelect";
  [
    ["none", "web.profile_advanced.post_action_none"],
    ["move", "web.profile_advanced.post_action_move"],
    ["unzip", "web.profile_advanced.post_action_unzip"],
  ].forEach(([value, key]) => {
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = t(key);
    opt.dataset.i18nKey = key;
    actionSelect.appendChild(opt);
  });
  actionRow.appendChild(actionLabel);
  actionRow.appendChild(actionSelect);
  form.appendChild(actionRow);

  const moveToRow = document.createElement("div");
  moveToRow.className = "field-row";
  const moveToLabel = document.createElement("label");
  moveToLabel.className = "field-label inline";
  moveToLabel.textContent = t("web.profile_advanced.move_to_label");
  moveToLabel.dataset.i18nKey = "web.profile_advanced.move_to_label";
  const moveToInput = document.createElement("input");
  moveToInput.type = "text";
  moveToInput.id = "arPostActionMoveToInput";
  const moveToBrowseBtn = document.createElement("button");
  moveToBrowseBtn.textContent = t("common.browse");
  moveToBrowseBtn.dataset.i18nKey = "common.browse";
  moveToBrowseBtn.addEventListener("click", () => {
    window.bridge.dialogs.browseFolder(moveToInput.value, (path) => {
      if (path) moveToInput.value = path;
    });
  });
  moveToRow.appendChild(moveToLabel);
  moveToRow.appendChild(moveToInput);
  moveToRow.appendChild(moveToBrowseBtn);
  form.appendChild(moveToRow);

  function refreshPostActionRowVisibility() {
    moveToRow.style.display = actionSelect.value === "move" ? "" : "none";
  }
  actionSelect.addEventListener("change", refreshPostActionRowVisibility);

  const formStatus = document.createElement("p");
  formStatus.id = "arFormStatus";
  formStatus.className = "status-line";
  form.appendChild(formStatus);

  const formBtnRow = document.createElement("div");
  formBtnRow.className = "field-row";
  const saveBtn = document.createElement("button");
  saveBtn.className = "start-btn";
  saveBtn.textContent = t("routing_rules.dialog_save_button");
  saveBtn.dataset.i18nKey = "routing_rules.dialog_save_button";
  saveBtn.addEventListener("click", () => {
    const name = nameInput.value.trim();
    const pattern = patternInput.value.trim();
    const destination = destInput.value.trim();
    if (!name || !pattern || !destination) {
      formStatus.textContent = t("routing_rules.missing_fields_message");
      return;
    }
    if (arEditingName && arEditingName !== name) {
      // Renamed: drop the old entry first so it isn't left behind
      // alongside the new one under a different name.
      window.bridge.profileAdvanced.deleteRoutingRule(arEditingName);
    }
    window.bridge.profileAdvanced.saveRoutingRule(
      name,
      pattern,
      fieldSelect.value,
      destination,
      actionSelect.value,
      moveToInput.value.trim()
    );
    arCloseForm();
    arReloadRules();
  });
  formBtnRow.appendChild(saveBtn);
  const cancelBtn = document.createElement("button");
  cancelBtn.textContent = t("common.cancel");
  cancelBtn.dataset.i18nKey = "common.cancel";
  cancelBtn.addEventListener("click", arCloseForm);
  formBtnRow.appendChild(cancelBtn);
  form.appendChild(formBtnRow);

  section.appendChild(form);
  container.appendChild(section);
}

// ------------------------------------------------------------ settings profiles

let arProfiles = [];

function arRefreshProfileCombo(selectName) {
  const combo = document.getElementById("apProfileSelect");
  combo.replaceChildren();
  // The network-profile-switch section (below) picks a profile from the
  // same list -- kept in sync here rather than duplicating the reload call,
  // guarded since this runs before that section exists on the very first
  // page build. A single pass builds each <option> once and clones it into
  // the second select instead of iterating arProfiles twice.
  const anpSelect = document.getElementById("anpProfileSelect");
  if (anpSelect) anpSelect.replaceChildren();
  arProfiles.forEach((profile) => {
    const opt = document.createElement("option");
    opt.value = profile.name;
    opt.textContent = profile.name;
    combo.appendChild(opt);
    if (anpSelect) anpSelect.appendChild(opt.cloneNode(true));
  });
  if (selectName) combo.value = selectName;
  const hasProfiles = arProfiles.length > 0;
  document.getElementById("apApplyBtn").disabled = !hasProfiles;
  document.getElementById("apDeleteBtn").disabled = !hasProfiles;
}

function arReloadProfiles(selectName) {
  window.bridge.profileAdvanced.listSettingsProfiles((profiles) => {
    arProfiles = profiles;
    arRefreshProfileCombo(selectName);
  });
}

function arBuildProfilesSection(container) {
  const section = document.createElement("div");
  section.className = "profile-section";
  section.appendChild(arSectionHeading("web.profile_advanced.settings_profiles_heading"));

  const intro = document.createElement("p");
  intro.className = "field-note";
  intro.textContent = t("settings_profiles.intro");
  intro.dataset.i18nKey = "settings_profiles.intro";
  section.appendChild(intro);

  const comboRow = document.createElement("div");
  comboRow.className = "field-row";
  const comboLabel = document.createElement("label");
  comboLabel.className = "field-label inline";
  comboLabel.textContent = t("settings_profiles.profile_label");
  comboLabel.dataset.i18nKey = "settings_profiles.profile_label";
  const combo = document.createElement("select");
  combo.id = "apProfileSelect";
  comboRow.appendChild(comboLabel);
  comboRow.appendChild(combo);
  section.appendChild(comboRow);

  const btnRow = document.createElement("div");
  btnRow.className = "field-row";
  const applyBtn = document.createElement("button");
  applyBtn.id = "apApplyBtn";
  applyBtn.className = "start-btn";
  applyBtn.textContent = t("settings_profiles.apply_button");
  applyBtn.dataset.i18nKey = "settings_profiles.apply_button";
  btnRow.appendChild(applyBtn);
  const saveAsBtn = document.createElement("button");
  saveAsBtn.id = "apSaveAsBtn";
  saveAsBtn.textContent = t("settings_profiles.save_as_button");
  saveAsBtn.dataset.i18nKey = "settings_profiles.save_as_button";
  btnRow.appendChild(saveAsBtn);
  const deleteBtn = document.createElement("button");
  deleteBtn.id = "apDeleteBtn";
  deleteBtn.textContent = t("settings_profiles.delete_button");
  deleteBtn.dataset.i18nKey = "settings_profiles.delete_button";
  btnRow.appendChild(deleteBtn);
  section.appendChild(btnRow);

  const status = document.createElement("p");
  status.id = "apStatus";
  status.className = "status-line";
  section.appendChild(status);

  applyBtn.addEventListener("click", () => {
    const name = combo.value;
    if (!name) return;
    window.bridge.profileAdvanced.applyProfile(name, (result) => {
      status.textContent = result.ok ? t("web.profile_advanced.profile_applied") : result.error || t("web.profile_advanced.profile_apply_error");
    });
  });

  saveAsBtn.addEventListener("click", () => {
    const name = (prompt(t("settings_profiles.save_as_label")) || "").trim();
    if (!name) return;
    window.bridge.profileAdvanced.saveCurrentAsProfile(name, () => {
      status.textContent = t("web.profile_advanced.profile_saved");
      arReloadProfiles(name);
    });
  });

  deleteBtn.addEventListener("click", () => {
    const name = combo.value;
    if (!name) return;
    if (!confirm(t("settings_profiles.delete_confirm_message", { name }))) return;
    window.bridge.profileAdvanced.deleteSettingsProfile(name);
    status.textContent = "";
    arReloadProfiles();
  });

  container.appendChild(section);
}

// ------------------------------------------------- network profile auto-switch

function anpRenderAssociations(list) {
  const box = document.getElementById("anpList");
  box.replaceChildren();
  if (!list.length) {
    const note = document.createElement("p");
    note.className = "empty-note";
    note.textContent = t("web.profile_advanced.no_network_associations");
    box.appendChild(note);
    return;
  }
  list.forEach((assoc) => {
    const row = document.createElement("div");
    row.className = "row";

    const ssidEl = document.createElement("span");
    ssidEl.className = "row-name";
    ssidEl.textContent = assoc.ssid;
    ssidEl.title = assoc.ssid;
    row.appendChild(ssidEl);

    const profileEl = document.createElement("span");
    profileEl.textContent = assoc.profileName;
    profileEl.title = assoc.profileName;
    row.appendChild(profileEl);

    const actions = document.createElement("div");
    actions.className = "row-actions";
    const removeBtn = document.createElement("button");
    removeBtn.textContent = "✕";
    removeBtn.addEventListener("click", () => {
      window.bridge.profileAdvanced.deleteNetworkProfileAssociation(assoc.ssid);
      // Fire-and-forget mutation with a known result -- filter the list
      // this render already has (in closure) and re-render, instead of a
      // round-trip re-fetch of what was just removed locally.
      anpRenderAssociations(list.filter((a) => a.ssid !== assoc.ssid));
    });
    actions.appendChild(removeBtn);
    row.appendChild(actions);

    box.appendChild(row);
  });
}

function anpReloadAssociations() {
  window.bridge.profileAdvanced.listNetworkProfileAssociations((list) => {
    anpRenderAssociations(list);
  });
}

function anpBuildSection(container) {
  const section = document.createElement("div");
  section.className = "profile-section";
  section.appendChild(arSectionHeading("web.profile_advanced.network_profile_switch_heading"));

  const intro = document.createElement("p");
  intro.className = "field-note";
  intro.textContent = t("web.profile_advanced.network_switch_intro");
  intro.dataset.i18nKey = "web.profile_advanced.network_switch_intro";
  section.appendChild(intro);

  const { row: enabledRow, check: enabledCheck } = paCheckboxRow(
    "anpEnabled",
    "web.profile_advanced.network_switch_enabled_checkbox"
  );
  section.appendChild(enabledRow);
  enabledCheck.addEventListener("change", () => {
    window.bridge.profileAdvanced.setNetworkProfileSwitchEnabled(enabledCheck.checked, () => {});
  });
  window.bridge.profileAdvanced.getNetworkProfileSwitchSettings((values) => {
    enabledCheck.checked = values.enabled;
  });

  const addRow = document.createElement("div");
  addRow.className = "field-row";
  const ssidInput = document.createElement("input");
  ssidInput.type = "text";
  ssidInput.id = "anpSsidInput";
  ssidInput.placeholder = t("web.profile_advanced.ssid_placeholder");
  ssidInput.dataset.i18nPlaceholder = "web.profile_advanced.ssid_placeholder";
  addRow.appendChild(ssidInput);

  const profileSelect = document.createElement("select");
  profileSelect.id = "anpProfileSelect";
  addRow.appendChild(profileSelect);

  const addBtn = document.createElement("button");
  addBtn.textContent = t("web.profile_advanced.associate_button");
  addBtn.dataset.i18nKey = "web.profile_advanced.associate_button";
  addRow.appendChild(addBtn);
  section.appendChild(addRow);

  const addStatus = document.createElement("p");
  addStatus.className = "status-line";
  addStatus.id = "anpAddStatus";
  section.appendChild(addStatus);

  const list = document.createElement("div");
  list.id = "anpList";
  list.className = "listbox";
  section.appendChild(list);

  addBtn.addEventListener("click", () => {
    const ssid = ssidInput.value.trim();
    const profileName = profileSelect.value;
    window.bridge.profileAdvanced.saveNetworkProfileAssociation(ssid, profileName, (result) => {
      addStatus.textContent = result.error || "";
      if (result.ok) {
        ssidInput.value = "";
        anpReloadAssociations();
      }
    });
  });

  container.appendChild(section);

  // Populated for real once arReloadProfiles() (called from
  // wireProfileAdvanced, after this section is built) resolves -- see
  // arRefreshProfileCombo, which keeps this <select> in sync with the
  // settings-profile list from then on.
}

function wireProfileAdvanced() {
  const container = document.getElementById("profileAdvancedContainer");
  arBuildRulesSection(container);
  arBuildProfilesSection(container);
  anpBuildSection(container);
  arReloadRules();
  arReloadProfiles();
  anpReloadAssociations();
}
