/* Foundry 13. No combat hooks: all switches are explicit user actions. */
export const MODULE_ID = "wowmap-poses";
let queue = Promise.resolve();

export function variantsFor(document) {
  const variants = document.getFlag("wowmap", "poseVariants")
    ?? document.actor?.getFlag("wowmap", "poseVariants");
  if (!variants || typeof variants !== "object") return null;
  for (const state of ["normal", "combat"]) {
    const variant = variants[state];
    if (!variant || typeof variant.token !== "string" || !variant.token.trim()) return null;
    if (variant.portrait != null && (typeof variant.portrait !== "string" || !variant.portrait.trim())) return null;
  }
  return variants;
}

function preload(path) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    const timeout = setTimeout(() => reject(new Error("Не удалось загрузить изображение за 15 секунд: " + path)), 15000);
    image.onload = () => { clearTimeout(timeout); resolve(); };
    image.onerror = () => { clearTimeout(timeout); reject(new Error("Изображение не найдено: " + path)); };
    image.src = path;
  });
}

async function applyPose(token, state) {
  const document = token?.document ?? token;
  if (!document || typeof document.update !== "function") throw new Error("Нужен токен на сцене.");
  if (!["normal", "combat"].includes(state)) throw new Error("Неизвестная поза.");
  const variants = variantsFor(document);
  if (!variants) throw new Error("Для этого токена не подготовлены два облика.");
  const selected = variants[state];
  const actor = document.actor;
  if (!document.isOwner || (selected.portrait && (!actor || !actor.isOwner))) {
    throw new Error("Недостаточно прав на изменение токена или его портрета.");
  }
  // Check both files before changing either document.
  await Promise.all([preload(selected.token), ...(selected.portrait ? [preload(selected.portrait)] : [])]);
  const previous = {"texture.src": document.texture.src, "flags.wowmap.pose": document.getFlag("wowmap", "pose") ?? "normal"};
  await document.update({"texture.src": selected.token, "flags.wowmap.pose": state});
  try {
    if (selected.portrait && actor.img !== selected.portrait) await actor.update({img: selected.portrait});
  } catch (error) {
    // A portrait failure must not leave a misleading successful token switch.
    try { await document.update(previous); }
    catch (rollbackError) { console.error(MODULE_ID, "Не удалось вернуть изображение токена", rollbackError); }
    throw error;
  }
  return state;
}

export function setPose(token, state) {
  // Serialize requests, including linked tokens sharing a portrait actor.
  const task = queue.then(() => applyPose(token, state));
  queue = task.catch(() => {});
  return task;
}

export function togglePose(token) {
  const document = token?.document ?? token;
  const task = queue.then(() => applyPose(token, document?.getFlag("wowmap", "pose") === "combat" ? "normal" : "combat"));
  queue = task.catch(() => {});
  return task;
}

export function renderHUD(hud, html) {
  const document = hud.object?.document;
  if (!document?.isOwner || !variantsFor(document)) return;
  const root = html instanceof HTMLElement ? html : html?.[0];
  if (!root?.querySelector || root.querySelector(".wowmap-pose-toggle")) return;
  const column = root.querySelector(".col.right") ?? root.querySelector(".right");
  if (!column) return;
  const button = window.document.createElement("button");
  button.type = "button";
  button.className = "control-icon wowmap-pose-toggle";
  const combat = document.getFlag("wowmap", "pose") === "combat";
  button.title = combat ? "Вернуть обычный облик" : "Включить боевой облик";
  button.setAttribute("aria-label", button.title);
  button.setAttribute("aria-pressed", String(combat));
  button.innerHTML = '<i class="fas fa-person-rays" aria-hidden="true"></i>';
  button.addEventListener("click", async event => {
    event.preventDefault(); event.stopPropagation(); button.disabled = true;
    try { await togglePose(hud.object); hud.render(); }
    catch (error) { ui.notifications.error(error.message); console.error(MODULE_ID, error); }
    finally { button.disabled = false; }
  });
  column.append(button);
}

if (typeof Hooks !== "undefined") {
  Hooks.once("init", () => {
    game.modules.get(MODULE_ID).api = {setPose, togglePose, variantsFor};
  });
  Hooks.on("renderTokenHUD", renderHUD);
}
