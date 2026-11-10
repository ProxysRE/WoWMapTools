/* Foundry 13 / dnd5e 5.3.3 visuals. Does not roll, consume, move or damage. */
import {BINDINGS} from './warcraft-visual-bindings.mjs';
export const ID = "wow-dnd5e";
export const PROFILES = Object.freeze({
  "wow.holy.heal": Object.freeze({kind: "burst", file: "modules/wow-dnd5e/assets/effects/holy-heal.webm", widthCells: 2.2, duration: 2000}),
  "wow.nature.heal": Object.freeze({kind: "burst", file: "modules/wow-dnd5e/assets/effects/nature-heal.webm", widthCells: 2.2, duration: 2000}),
  "wow.frost.beam": Object.freeze({kind: "beam", file: "modules/wow-dnd5e/assets/effects/frost-beam.webm", heightCells: 0.9, fileHeight: 128, duration: 900}),
  "wow.shadow.beam": Object.freeze({kind: "beam", file: "modules/wow-dnd5e/assets/effects/shadow-beam.webm", heightCells: 0.9, fileHeight: 128, duration: 900}),
  "wow.nature.beam": Object.freeze({kind: "beam", file: "modules/wow-dnd5e/assets/effects/nature-beam.webm", heightCells: 0.9, fileHeight: 128, duration: 900}),
  "wow.drain.beam": Object.freeze({kind: "beam", file: "modules/wow-dnd5e/assets/effects/drain-beam.webm", heightCells: 0.9, fileHeight: 128, duration: 900}),
  "wow.frost.projectile": Object.freeze({file: "modules/wow-dnd5e/assets/effects/frost-projectile.webm", widthCells: 6, anchor: {x: 0.625, y: 0.5}, speedCells: 8}),
  "wow.shadow.projectile": Object.freeze({file: "modules/wow-dnd5e/assets/effects/shadow-projectile.webm", widthCells: 6, anchor: {x: 0.625, y: 0.5}, speedCells: 8}),
  "wow.fel.projectile": Object.freeze({file: "modules/wow-dnd5e/assets/effects/fel-projectile.webm", widthCells: 6, anchor: {x: 0.625, y: 0.5}, speedCells: 8}),
  "wow.fire.projectile": Object.freeze({
    file: "modules/wow-dnd5e/assets/effects/fire-projectile.webm",
    widthCells: 6, anchor: {x: 0.625, y: 0.5}, speedCells: 8
  })
});
const seen = new Map();

export function visualFor(activity) {
  const item=activity?.item;
  const binding=item?.getFlag(ID, 'visuals');
  if(binding?.disabled)return null;
  let value;
  if(Object.hasOwn(binding?.activities??{},activity.id))value=binding.activities[activity.id];
  else {
    // Old imported items retain their canonical compendium UUID even after renaming.
    const origin=item?._stats?.compendiumSource??item?.getFlag('core','sourceId');
    const actorOrigin=item?.actor?._stats?.compendiumSource??item?.actor?.getFlag?.('core','sourceId');
    const key=origin??(actorOrigin&&item.id?actorOrigin+'.Item.'+item.id:null);
    value=BINDINGS[key]?.activities?.[activity.id];
  }
  if(!value||!Object.hasOwn(PROFILES,value.profile??'')||!['token','template','recipients','self'].includes(value.mode)||value.activityType!==activity.type)return null;
  if (['recipients','self'].includes(value.mode) && PROFILES[value.profile].kind !== 'burst') return null;
  if (value.mode === 'recipients' && (!Number.isInteger(value.maxTargets) || value.maxTargets < 1 || value.maxTargets > 6)) return null;
  return value;
}

function environment() {
  if (Number(game.release.generation) !== 13 || game.system.id !== "dnd5e" || game.system.version !== "5.3.3") {
    throw new Error("Пилот подготовлен для Foundry 13 и dnd5e 5.3.3.");
  }
  if (!canvas?.ready || !canvas.scene) throw new Error("Откройте сцену с токенами.");
  if (!game.modules.get("sequencer")?.active || typeof Sequence !== "function") {
    throw new Error("Включите совместимую с Foundry 13 версию Sequencer.");
  }
}

export function sourceFor(actor) {
  if (!actor) throw new Error("У способности нет владельца.");
  const candidates = canvas.tokens.placeables.filter(t => t.actor?.uuid === actor.uuid);
  const controlled = candidates.filter(t => t.controlled);
  if (controlled.length === 1) return controlled[0];
  if (candidates.length === 1) return candidates[0];
  throw new Error("Выберите ровно один токен владельца способности на этой сцене.");
}

function point(token) {
  if (!token?.document || token.document.parent?.id !== canvas.scene.id || !token.center) {
    throw new Error("Источник и цель должны быть токенами текущей сцены.");
  }
  if (!game.user.isGM && !token.isVisible) throw new Error("Токен недоступен для просмотра.");
  const result = {x: Number(token.center.x), y: Number(token.center.y)};
  if (!Number.isFinite(result.x) || !Number.isFinite(result.y)) throw new Error("Некорректные координаты токена.");
  return result;
}

export async function play({source, target, destination, profile = "wow.fire.projectile"}) {
  environment();
  if (!Object.hasOwn(PROFILES, profile)) throw new Error("Неизвестный визуальный профиль.");
  if (!source?.document?.isOwner) throw new Error("Нужно владение токеном источника.");
  const p = PROFILES[profile];
  if (p.kind === 'burst') {
    point(source);
    const at = point(target ?? source), grid = canvas.grid.size;
    if (!Number.isFinite(grid) || grid <= 0) throw new Error("Некорректный масштаб сцены.");
    const recipient = target ?? source;
    const tokenSize = Math.max(1, Number(recipient.document.width) || 1, Number(recipient.document.height) || 1);
    await new Sequence().effect().file(p.file).atLocation(at)
      .size(p.widthCells * grid * tokenSize).spriteAnchor({x:0.5,y:0.5})
      .duration(p.duration).fadeIn(60).fadeOut(160).play();
    return {profile, at, duration:p.duration};
  }
  if (target && (source === target || source.document.uuid === target.document?.uuid)) throw new Error("Для снаряда выберите другой токен.");
  const from=point(source);
  const to=target?point(target):{x:Number(destination?.x),y:Number(destination?.y)};
  if(!target&&(destination?.sceneId!==canvas.scene.id||!Number.isFinite(to.x)||!Number.isFinite(to.y)))throw new Error('Нужен шаблон текущей сцены.');
  const distance = Math.hypot(to.x - from.x, to.y - from.y);
  if (distance < 1) throw new Error("Источник и цель находятся в одной точке.");
  const grid = canvas.grid.size;
  if (!Number.isFinite(grid) || grid <= 0) throw new Error("Некорректный масштаб сцены.");
  if (p.kind === 'beam') {
    const sequence = new Sequence().effect().file(p.file).atLocation(from)
      .template({gridSize: p.fileHeight, startPoint: 0, endPoint: 0})
      .stretchTo(to, {onlyX: true, cacheLocation: true})
      .scale({x: 1, y: grid * p.heightCells / p.fileHeight})
      .duration(p.duration).fadeIn(60).fadeOut(120);
    await sequence.play();
    return {profile, from, to, duration: p.duration};
  }
  const speed = grid * p.speedCells;
  const duration = Math.max(150, Math.min(5000, distance / speed * 1000));
  // Keep flight duration and speed consistent at both short and long distances.
  const sequence = new Sequence().effect()
    .file(p.file).atLocation(from).moveTowards(to, {rotate: true, cacheLocation: true})
    .moveSpeed(distance / (duration / 1000)).duration(duration)
    .size(p.widthCells * grid).spriteAnchor(p.anchor)
    .fadeIn(Math.min(50, duration / 4)).fadeOut(Math.min(80, duration / 4));
  await sequence.play();
  return {profile, from, to, duration};
}

export async function testSelected() {
  environment();
  const selected = canvas.tokens.controlled;
  const targets = [...game.user.targets];
  if (selected.length !== 1 || targets.length !== 1) {
    throw new Error("Выберите один свой токен и назначьте ровно одну цель клавишей T.");
  }
  return play({source: selected[0], target: targets[0]});
}

export async function bind(item, activityId, profile = "wow.fire.projectile") {
  if (!item?.isOwner) throw new Error("Недостаточно прав на изменение предмета.");
  if (!item.system?.activities?.get(activityId)) throw new Error("Активность предмета не найдена.");
  if (profile !== null && !Object.hasOwn(PROFILES, profile)) throw new Error("Неизвестный визуальный профиль.");
  const current = item.getFlag(ID, "visuals");
  const activities = {...current?.activities};
  const activity=item.system.activities.get(activityId);
  if (profile === null) activities[activityId]=null;
  else activities[activityId]=PROFILES[profile].kind==='burst' ? {profile,mode:'recipients',activityType:activity.type,maxTargets:1} : {profile,mode:'token',activityType:activity.type};
  await item.setFlag(ID, "visuals", {version: 1, activities});
}

export async function onUse(activity, config, results) {
  if (!game.settings.get(ID, "visualEffects")||!game.modules.get('sequencer')?.active) return;
  const visual=visualFor(activity);
  if(!visual)return;
  // Explicit legacy pilot bindings take priority to avoid two animation engines.
  if(game.modules.get('wowmap-effects')?.active&&activity.item?.getFlag('wowmap','visuals')?.activities?.[activity.id]) {
    try {if(game.settings.get('wowmap-effects','automatic'))return;}catch{}
  }
  // This hook runs after completed use, not canceled dialogs or roll/damage hooks.
  // Only the author of the use message initiates Sequencer's network broadcast.
  const message = results?.message;
  if (!message?.uuid || message.author?.id !== game.user.id) return;
  const now = Date.now();
  for (const [key, time] of seen) if (now - time > 60000) seen.delete(key);
  const key = message.uuid + ":" + activity.id;
  if (seen.has(key)) return;
  seen.set(key, now);
  try {
    const source=sourceFor(activity.actor??activity.item.actor);
    if(visual.mode==='self') {
      await play({source,profile:visual.profile});
    } else if(visual.mode==='recipients') {
      const targets=[...game.user.targets];
      if(targets.length<1 || targets.length>visual.maxTargets)throw new Error(`Для лечения назначьте от 1 до ${visual.maxTargets} целей (можно свой токен).`);
      // Validate every recipient before broadcasting anything: no partial play on invalid scenes.
      for(const target of targets)point(target);
      await Promise.all(targets.map(target=>play({source,target,profile:visual.profile})));
    } else if(visual.mode==='template'){
      const templates=results.templates??[];
      if(templates.length!==1)throw new Error('Разместите один шаблон заклинания; снаряд летит к его центру.');
      const doc=templates[0].document??templates[0];
      await play({source,destination:{x:doc.x,y:doc.y,sceneId:doc.parent?.id},profile:visual.profile});
    } else {
      const targets=[...game.user.targets];
      if(targets.length!==1)throw new Error('Для снаряда назначьте ровно одну цель.');
      await play({source,target:targets[0],profile:visual.profile});
    }
  } catch (error) {
    ui.notifications.warn("WoWMap: " + error.message);
    console.error(ID, error);
  }
}

if (typeof Hooks !== "undefined") {
  Hooks.once("init", () => {
    game.settings.register(ID, "visualEffects", {
      name: "Визуальные эффекты WoW", hint: "Готовые привязки способностей. Нужен Sequencer для Foundry 13; без него игровая механика работает как прежде.",
      scope: "world", config: true, type: Boolean, default: true
    });
    const module=game.modules.get(ID);module.api??={};
    module.api.visuals={play,testSelected,bind,profiles:PROFILES};
  });
  Hooks.on("dnd5e.postUseActivity", (activity, config, results) => {
    // Returning undefined preserves the system's subsequent primary action.
    void onUse(activity, config, results);
  });
}
