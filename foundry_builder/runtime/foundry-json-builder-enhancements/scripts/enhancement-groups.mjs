const MODULE_ID = "foundry-json-builder-enhancements";
const ATTUNEMENT_THRESHOLD = 4;
const GROUP_ALIASES = new Map([
  ["elemental_damage", "additional_damage"],
]);
const expandingEffects = new Set();
const attunementUpdates = new Set();
const attunementQueues = new Map();

function enhancementMetadata(effect) {
  return effect.getFlag(MODULE_ID, "enhancement") ?? null;
}

function itemPolicy(item) {
  return item?.getFlag(MODULE_ID, "itemPolicy") ?? null;
}

function canonicalGroup(group) {
  const value = String(group ?? "");
  return GROUP_ALIASES.get(value) ?? value;
}

function occupiedGroups(metadata) {
  const primaryGroup = canonicalGroup(metadata?.group);
  if (primaryGroup === "signature_property") {
    return new Set(["signature_property"]);
  }
  const configured = metadata?.occupiesGroups ?? metadata?.occupies_groups;
  const values = Array.isArray(configured) && configured.length
    ? configured
    : [primaryGroup];
  return new Set(
    values
      .map(canonicalGroup)
      .filter((group) => group.length)
  );
}

function policyMismatch(effect) {
  const metadata = enhancementMetadata(effect);
  const item = effect.parent;
  if (!metadata?.group || item?.documentName !== "Item") return null;

  const group = canonicalGroup(metadata.group);
  if (group === "material_property") {
    return (
      "свойство материала назначается только при создании или перековке "
      + "предмета и не устанавливается обычным усилителем"
    );
  }

  const policy = itemPolicy(item);
  if (!policy) {
    if (String(item.system?.rarity ?? "").toLowerCase() === "artifact") {
      return (
        "артефакт без явной политики усилений по умолчанию закрыт; "
        + "задайте mode=open или mode=restricted при создании предмета"
      );
    }
    return null;
  }

  const mode = String(policy.mode ?? "open");
  if (mode === "locked") {
    const reason = String(policy.reason ?? "").trim();
    return reason || "предмет закрыт для внешних усилений";
  }

  const reservedGroups = new Set(
    (Array.isArray(policy.reservedGroups) ? policy.reservedGroups : [])
      .map(canonicalGroup)
  );
  if (reservedGroups.has(group)) {
    return `группа ${group} занята врождённым свойством предмета`;
  }

  if (mode === "restricted") {
    const allowedGroups = new Set(
      (Array.isArray(policy.allowedGroups) ? policy.allowedGroups : [])
        .map(canonicalGroup)
    );
    if (!allowedGroups.has(group)) {
      return `политика предмета не разрешает группу ${group}`;
    }
  }
  return null;
}

function targetMismatch(effect) {
  const metadata = enhancementMetadata(effect);
  const target = metadata?.target;
  const item = effect.parent;
  if (item?.documentName !== "Item") return null;

  const policyError = policyMismatch(effect);
  if (policyError) return policyError;
  if (!target) return null;

  const itemTypes = Array.isArray(target.itemTypes) ? target.itemTypes : [];
  if (itemTypes.length && !itemTypes.includes(item.type)) {
    return `требуется тип ${itemTypes.join(", ")}`;
  }

  const systemTypes = Array.isArray(target.systemTypes)
    ? target.systemTypes
    : [];
  const actualSystemType = String(item.system?.type?.value ?? "");
  if (systemTypes.length && !systemTypes.includes(actualSystemType)) {
    return (
      `требуется подтип ${systemTypes.join(", ")}, `
      + `у цели подтип ${actualSystemType || "не задан"}`
    );
  }
  return null;
}

function enforceTargetRestrictions(effect, _data, _options, userId) {
  if (game.user.id !== userId || effect.type !== "enchantment") return;
  const mismatch = targetMismatch(effect);
  if (!mismatch) return;
  ui.notifications.error(
    `${effect.name}: неподходящая цель — ${mismatch}.`
  );
  return false;
}

function attunementDemand(item) {
  let weight = 0;
  let required = false;
  for (const effect of item.effects ?? []) {
    if (effect.type !== "enchantment" || effect.disabled) continue;
    const metadata = enhancementMetadata(effect);
    const attunement = metadata?.attunement;
    if (!attunement) continue;
    const value = Number(attunement.weight ?? 0);
    if (Number.isFinite(value) && value > 0) weight += value;
    required ||= attunement.required === true;
  }
  return {
    weight,
    required: required || weight >= ATTUNEMENT_THRESHOLD,
  };
}

async function guardedItemUpdate(item, update) {
  attunementUpdates.add(item.uuid);
  try {
    await item.update(update);
  } finally {
    attunementUpdates.delete(item.uuid);
  }
}

async function reconcileAttunement(item) {
  if (item?.documentName !== "Item") return;
  const demand = attunementDemand(item);
  const state = item.getFlag(MODULE_ID, "attunement") ?? null;
  const current = item.system.attunement ?? "";
  const flagPath = `flags.${MODULE_ID}.attunement`;
  const deleteFlagPath = `flags.${MODULE_ID}.-=attunement`;

  if (demand.required) {
    if (state?.manualOverride === true || current === "required") return;
    await guardedItemUpdate(item, {
      "system.attunement": "required",
      [flagPath]: {
        managed: true,
        previous: current,
        weight: demand.weight,
      },
    });
    ui.notifications.info(
      `${item.name}: усиления требуют настройки `
      + `(вес ${demand.weight}/${ATTUNEMENT_THRESHOLD}).`
    );
    return;
  }

  if (state?.managed === true) {
    const update = {[deleteFlagPath]: null};
    if (current === "required") {
      update["system.attunement"] = state.previous ?? "";
    }
    await guardedItemUpdate(item, update);
    ui.notifications.info(
      `${item.name}: автоматическое требование настройки снято.`
    );
  } else if (state?.manualOverride === true) {
    await guardedItemUpdate(item, {[deleteFlagPath]: null});
  }
}

function queueAttunementReconcile(item) {
  if (item?.documentName !== "Item") return Promise.resolve();
  const key = item.uuid;
  const previous = attunementQueues.get(key) ?? Promise.resolve();
  const current = previous
    .catch(() => undefined)
    .then(() => reconcileAttunement(item))
    .finally(() => {
      if (attunementQueues.get(key) === current) {
        attunementQueues.delete(key);
      }
    });
  attunementQueues.set(key, current);
  return current;
}

async function replaceSameGroup(effect) {
  const metadata = enhancementMetadata(effect);
  const item = effect.parent;
  if (!metadata?.group || item?.documentName !== "Item") return;
  const replacementGroups = occupiedGroups(metadata);

  const replaced = item.effects.filter((candidate) => {
    if (candidate.id === effect.id) return false;
    if (candidate.type !== "enchantment" || candidate.disabled) return false;
    const candidateMetadata = enhancementMetadata(candidate);
    const candidateGroups = occupiedGroups(candidateMetadata);
    return [...replacementGroups].some((group) => candidateGroups.has(group));
  });
  if (!replaced.length) return;

  try {
    await item.deleteEmbeddedDocuments(
      "ActiveEffect",
      replaced.map((candidate) => candidate.id)
    );
    const oldNames = replaced.map((candidate) => candidate.name).join(", ");
    ui.notifications.info(
      `${effect.name}: заменены конфликтующие усиления (${oldNames}).`
    );
  } catch (error) {
    console.error(`${MODULE_ID} | Не удалось заменить усиление группы.`, error);
    ui.notifications.error(
      `${effect.name}: не удалось удалить прежнее усиление той же группы.`
    );
  }
}

function remapRiderDocuments(component) {
  const activityMap = new Map();
  const effectMap = new Map();
  const activities = foundry.utils.deepClone(component.activities ?? []);
  const effects = foundry.utils.deepClone(component.effects ?? []);

  for (const activity of activities) {
    const oldId = activity._id;
    activity._id = foundry.utils.randomID();
    activityMap.set(oldId, activity._id);
  }
  for (const riderEffect of effects) {
    const oldId = riderEffect._id;
    riderEffect._id = foundry.utils.randomID();
    effectMap.set(oldId, riderEffect._id);
  }
  for (const activity of activities) {
    for (const reference of activity.effects ?? []) {
      if (effectMap.has(reference._id)) {
        reference._id = effectMap.get(reference._id);
      }
    }
  }

  const enchantment = foundry.utils.deepClone(component.effect);
  enchantment._id = foundry.utils.randomID();
  enchantment.disabled = false;
  const riders = enchantment.flags?.dnd5e?.enchantment?.riders;
  if (riders) {
    riders.activity = (riders.activity ?? []).map(
      (id) => activityMap.get(id) ?? id
    );
    riders.effect = (riders.effect ?? []).map(
      (id) => effectMap.get(id) ?? id
    );
  }
  const metadata = enchantment.flags?.[MODULE_ID]?.enhancement;
  if (metadata) {
    delete metadata.bundle;
    metadata.managedRiders = {
      activity: activities.map((activity) => activity._id),
      effect: effects.map((effect) => effect._id),
    };
  }
  return { activities, effects, enchantment };
}

async function createRiderActivities(item, activities) {
  if (!activities.length) return;
  const update = {};
  for (const activity of activities) {
    update[`system.activities.${activity._id}`] = activity;
  }
  await item.update(update);
}

async function expandBundle(effect) {
  const metadata = enhancementMetadata(effect);
  const bundle = metadata?.bundle;
  const item = effect.parent;
  if (
    !bundle?.components?.length
    || item?.documentName !== "Item"
    || expandingEffects.has(effect.uuid)
  ) return;

  expandingEffects.add(effect.uuid);
  const createdComponentIds = [];
  const createdRiderEffectIds = [];
  const createdActivityIds = [];
  try {
    for (const rawComponent of bundle.components) {
      const component = remapRiderDocuments(rawComponent);
      if (component.effects.length) {
        const createdEffects = await item.createEmbeddedDocuments(
          "ActiveEffect",
          component.effects,
          { keepId: true }
        );
        createdRiderEffectIds.push(...createdEffects.map((entry) => entry.id));
      }
      await createRiderActivities(item, component.activities);
      createdActivityIds.push(
        ...component.activities.map((activity) => activity._id)
      );
      const [createdComponent] = await item.createEmbeddedDocuments(
        "ActiveEffect",
        [component.enchantment],
        { keepId: true }
      );
      createdComponentIds.push(createdComponent.id);
    }

    const normalized = foundry.utils.deepClone(metadata);
    delete normalized.bundle;
    normalized.bundleId = bundle.id;
    await effect.update({
      name: bundle.primaryName || effect.name,
      [`flags.${MODULE_ID}.enhancement`]: normalized,
    });
    ui.notifications.info(
      `${bundle.name}: применено независимых усилений — `
      + `${bundle.components.length + 1}.`
    );
  } catch (error) {
    console.error(`${MODULE_ID} | Не удалось развернуть составное усиление.`, error);
    const existingComponents = createdComponentIds.filter(
      (id) => item.effects.get(id)
    );
    if (existingComponents.length) {
      await item.deleteEmbeddedDocuments("ActiveEffect", existingComponents);
    }
    const existingRiders = createdRiderEffectIds.filter(
      (id) => item.effects.get(id)
    );
    if (existingRiders.length) {
      await item.deleteEmbeddedDocuments("ActiveEffect", existingRiders);
    }
    const activityUpdate = {};
    for (const id of createdActivityIds) {
      activityUpdate[`system.activities.-=${id}`] = null;
    }
    if (Object.keys(activityUpdate).length) await item.update(activityUpdate);
    ui.notifications.error(
      `${bundle.name}: не удалось применить все компоненты усиления.`
    );
  } finally {
    expandingEffects.delete(effect.uuid);
  }
}

async function handleCreatedEnhancement(effect, _options, userId) {
  if (game.user.id !== userId) return;
  if (effect.type !== "enchantment" || effect.disabled) return;
  await replaceSameGroup(effect);
  await expandBundle(effect);
  await queueAttunementReconcile(effect.parent);
}

async function cleanupManagedRiders(effect, _options, userId) {
  if (game.user.id !== userId) return;
  const metadata = enhancementMetadata(effect);
  const item = effect.parent;
  const managed = metadata?.managedRiders;
  if (item?.documentName !== "Item") return;

  if (managed) {
    const activityUpdate = {};
    for (const id of managed.activity ?? []) {
      if (item.system.activities?.[id]) {
        activityUpdate[`system.activities.-=${id}`] = null;
      }
    }
    if (Object.keys(activityUpdate).length) await item.update(activityUpdate);

    const riderEffectIds = (managed.effect ?? []).filter(
      (id) => item.effects.get(id)
    );
    if (riderEffectIds.length) {
      await item.deleteEmbeddedDocuments("ActiveEffect", riderEffectIds);
    }
  }
  await queueAttunementReconcile(item);
}

async function handleUpdatedEnhancement(effect, _changes, _options, userId) {
  if (game.user.id !== userId) return;
  if (effect.type !== "enchantment") return;
  await queueAttunementReconcile(effect.parent);
}

async function preserveManualAttunement(item, changes, _options, userId) {
  if (game.user.id !== userId || attunementUpdates.has(item.uuid)) return;
  if (!foundry.utils.hasProperty(changes, "system.attunement")) return;
  const state = item.getFlag(MODULE_ID, "attunement");
  if (state?.managed !== true) return;

  const next = foundry.utils.getProperty(changes, "system.attunement");
  const deleteFlagPath = `flags.${MODULE_ID}.-=attunement`;
  if (next === "required") {
    await guardedItemUpdate(item, {[deleteFlagPath]: null});
  } else {
    await guardedItemUpdate(item, {
      [`flags.${MODULE_ID}.attunement`]: {
        managed: false,
        manualOverride: true,
      },
    });
  }
}

Hooks.on("createActiveEffect", handleCreatedEnhancement);
Hooks.on("preCreateActiveEffect", enforceTargetRestrictions);
Hooks.on("deleteActiveEffect", cleanupManagedRiders);
Hooks.on("updateActiveEffect", handleUpdatedEnhancement);
Hooks.on("updateItem", preserveManualAttunement);

Hooks.once("ready", () => {
  console.info(
    `${MODULE_ID} | Контроллер групп, политики предметов, материалов, `
    + `подтипов, составных усилений и настройки готов.`
  );
});
