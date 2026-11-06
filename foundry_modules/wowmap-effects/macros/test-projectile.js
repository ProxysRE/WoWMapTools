try {
  const api = game.modules.get("wowmap-effects")?.api;
  if (!api) throw new Error("Включите модуль WoWMap — эффекты способностей.");
  await api.testSelected();
} catch (error) { ui.notifications.error(error.message); }
