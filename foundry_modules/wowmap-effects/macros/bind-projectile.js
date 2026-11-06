try {
  const api = game.modules.get("wowmap-effects")?.api;
  if (!api) throw new Error("Включите WoWMap — эффекты способностей.");
  const tokens = canvas.tokens.controlled;
  if (tokens.length !== 1 || !tokens[0].document.isOwner) throw new Error("Выберите один свой токен.");
  const actor = tokens[0].actor;
  const entries = [...actor.items.values()].flatMap(item => [...(item.system.activities ?? [])].map(activity => ({item, activity})));
  if (!entries.length) throw new Error("У актёра нет предметов с активностями.");
  const escape = value => String(value).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const options = entries.map((e, i) => `<option value="${i}">${escape(e.item.name)} — ${escape(e.activity.name)}</option>`).join("");
  const selection = await foundry.applications.api.DialogV2.prompt({
    window: {title: "Назначить огненный снаряд"},
    content: `<p>Выберите конкретную активность. Переименование предмета не удалит привязку.</p><select name="entry">${options}</select><label><input type="checkbox" name="remove"> Снять привязку</label>`,
    ok: {label: "Сохранить", callback: (_event, button) => ({index: Number(button.form.elements.entry.value), remove: button.form.elements.remove.checked})},
    rejectClose: false
  });
  if (selection) {
    const entry = entries[selection.index];
    if (!entry) throw new Error("Активность не найдена.");
    await api.bind(entry.item, entry.activity.id, selection.remove ? null : "wow.fire.projectile");
    ui.notifications.info(selection.remove ? "Привязка снята." : "Снаряд назначен. Автозапуск включается в настройках модуля.");
  }
} catch (error) { ui.notifications.error(error.message); }
