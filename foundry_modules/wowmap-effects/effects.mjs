/* Foundry 13 / dnd5e 5.3.3 pilot. Does not roll, consume, move or damage. */
export const ID = "wowmap-effects";
export const PROFILES = Object.freeze({
  "wow.fire.projectile": Object.freeze({
    file: "modules/wowmap-effects/media/fire-projectile.webm",
    widthCells: 6, anchor: {x: 0.625, y: 0.5}, speedCells: 8
  })
});
const seen = new Map();

export function visualFor(activity) {
  const binding = activity?.item?.getFlag("wowmap", "visuals");
  const profile = binding?.activities?.[activity.id];
  return Object.hasOwn(PROFILES, profile ?? "") ? profile : null;
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

export async function play({source, target, profile = "wow.fire.projectile"}) {
  environment();
  if (!Object.hasOwn(PROFILES, profile)) throw new Error("Неизвестный визуальный профиль.");
  if (!source?.document?.isOwner) throw new Error("Нужно владение токеном источника.");
  if (source === target || source.document.uuid === target?.document?.uuid) throw new Error("Для снаряда выберите другой токен.");
  const from = point(source), to = point(target), p = PROFILES[profile];
  const distance = Math.hypot(to.x - from.x, to.y - from.y);
  if (distance < 1) throw new Error("Источник и цель находятся в одной точке.");
  const grid = canvas.grid.size;
  if (!Number.isFinite(grid) || grid <= 0) throw new Error("Некорректный масштаб сцены.");
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
  const current = item.getFlag("wowmap", "visuals");
  const activities = {...current?.activities};
  if (profile === null) delete activities[activityId]; else activities[activityId] = profile;
  await item.setFlag("wowmap", "visuals", {version: 1, activities});
}

export async function onUse(activity, config, results) {
  if (!game.settings.get(ID, "automatic")) return;
  const profile = visualFor(activity);
  if (!profile) return;
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
    const targets = [...game.user.targets];
    if (targets.length !== 1) throw new Error("Для пробного снаряда назначьте ровно одну цель.");
    await play({source: sourceFor(activity.actor ?? activity.item.actor), target: targets[0], profile});
  } catch (error) {
    ui.notifications.warn("WoWMap: " + error.message);
    console.error(ID, error);
  }
}

if (typeof Hooks !== "undefined") {
  Hooks.once("init", () => {
    game.settings.register(ID, "automatic", {
      name: "Автозапуск привязанных эффектов", hint: "Включайте после ручной проверки. Действует только на явно назначенные активности.",
      scope: "world", config: true, type: Boolean, default: false
    });
    game.modules.get(ID).api = {play, testSelected, bind, profiles: PROFILES};
  });
  Hooks.on("dnd5e.postUseActivity", (activity, config, results) => {
    // Returning undefined preserves the system's subsequent primary action.
    void onUse(activity, config, results);
  });
}
