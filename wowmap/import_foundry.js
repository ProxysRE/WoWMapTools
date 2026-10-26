// Paste into a Foundry VTT 13 Script macro and run as GM.
// Creates new actors and scenes only. Existing documents are never replaced or deleted.
(async () => {
  try {
    if (!game.user.isGM) throw new Error('Run this macro as Gamemaster.');
    if (Number(game.release.generation) !== 13) throw new Error('This export targets Foundry VTT 13.');
    const url = await foundry.applications.api.DialogV2.prompt({
      window: {title: 'Import WoWMapTools scenes'},
      content: '<label>Bundle path in Foundry Data<input name="url" value="__BUNDLE_URL__" required></label>',
      ok: {label: 'Check and import', callback: (event, button) => button.form.elements.url.value.trim()},
      rejectClose: false
    });
    if (!url) return;
    const response = await fetch(url, {cache: 'no-store'});
    if (!response.ok) throw new Error(`Cannot load bundle: HTTP ${response.status}`);
    const bundle = await response.json();
    if (bundle.format !== 'wowmap.foundry/1' || !Array.isArray(bundle.scenes) || !bundle.scenes.length) {
      throw new Error('Invalid WoWMapTools bundle.');
    }
    const data = foundry.utils.deepClone(bundle.scenes);
    const actors = foundry.utils.deepClone(bundle.actors || []);
    if (!Array.isArray(actors)) throw new Error('Invalid actors collection.');
    if (actors.length && (game.system.id !== 'dnd5e' || game.system.version !== (bundle.targets?.dnd5e || '5.3.3'))) {
      throw new Error('This populated bundle requires dnd5e ' + (bundle.targets?.dnd5e || '5.3.3'));
    }
    // Remap media paths if the uploaded folder differs from the default.
    const root = url.replace(/\/bundle\.json$/, '');
    if (root === url) throw new Error('Path must end with /bundle.json');
    const remap = path => path?.startsWith(bundle.mediaRoot + '/') ? root + path.slice(bundle.mediaRoot.length) : path;
    const files = new Set(bundle.externalMedia || []);
    const ids = new Set();
    const SceneClass = CONFIG.Scene.documentClass;
    const ActorClass = actors.length ? CONFIG.Actor.documentClass : null;
    const actorIds = new Set();
    for (const actor of actors) {
      if (actorIds.has(actor._id) || game.actors.has(actor._id)) throw new Error(`Actor ID already exists: ${actor.name}. Use a new export package id.`);
      actorIds.add(actor._id);
      if (actor.type !== 'npc') throw new Error('Population only supports NPC actors.');
      actor.folder = null;
      actor.img = remap(actor.img);
      if (actor.img) files.add(actor.img);
      if (actor.prototypeToken?.texture?.src) {
        actor.prototypeToken.texture.src = remap(actor.prototypeToken.texture.src);
        files.add(actor.prototypeToken.texture.src);
      }
      const model = new ActorClass(actor, {strict: true});
      model.validate({strict: true});
    }
    for (const scene of data) {
      if (ids.has(scene._id) || game.scenes.has(scene._id)) throw new Error(`Scene ID already exists: ${scene.name}. Use a new export package id.`);
      ids.add(scene._id);
      scene.background.src = remap(scene.background.src);
      files.add(scene.background.src);
      for (const tile of scene.tiles || []) {tile.texture.src = remap(tile.texture.src); files.add(tile.texture.src);}
      for (const token of scene.tokens || []) {
        if (!actorIds.has(token.actorId) && !game.actors.has(token.actorId)) throw new Error(`Unknown actor for token: ${token.name}`);
        if (token.texture?.src) {token.texture.src = remap(token.texture.src); files.add(token.texture.src);}
      }
      // Validate against the actual installed v13 core, including nested documents.
      const model = new SceneClass(scene, {strict: true});
      model.validate({strict: true});
      for (const region of model.regions) {
        region.validate({strict: true});
        for (const behavior of region.behaviors) {
          if (!CONFIG.RegionBehavior.dataModels[behavior.type]) throw new Error(`Unknown behavior: ${behavior.type}`);
          behavior.validate({strict: true});
          behavior.system.validate({strict: true});
        }
      }
    }
    for (const path of files) {
      const check = await fetch(path, {method: 'HEAD'});
      if (!check.ok) throw new Error(`Missing media: ${path} (HTTP ${check.status})`);
    }
    // Actors must exist before their linked tokens are created.
    if (actors.length) {
      const createdActors = await ActorClass.createDocuments(actors, {keepId: true, keepEmbeddedIds: true});
      if (createdActors.length !== actors.length) throw new Error('Only some actors were created; inspect the actor list before retrying.');
    }
    // Keep embedded IDs so cross-scene Region UUIDs remain valid.
    const created = await SceneClass.createDocuments(data, {keepId: true, keepEmbeddedIds: true});
    if (created.length !== data.length) throw new Error('Only some scenes were created; inspect the scene list before retrying.');
    for (const scene of created) {
      for (const region of scene.regions) {
        for (const behavior of region.behaviors) {
          if (behavior.type === 'teleportToken' && !await fromUuid(behavior.toObject().system.destination)) {
            throw new Error(`Scenes created, but teleport link needs checking: ${region.name}`);
          }
        }
      }
    }
    ui.notifications.info(`WoWMapTools: imported ${created.length} scenes and ${actors.length} actors.`);
  } catch (error) {
    console.error('WoWMapTools import', error);
    ui.notifications.error(`WoWMapTools: ${error.message}`, {permanent: true});
  }
})();
