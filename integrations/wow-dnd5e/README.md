# WoW DnD5e visual adapter 0.40.26

Code mirror for the canonical book module, not a separately installable module.
The complete source archive and built module are delivered separately.

- 144 explicit activity bindings: 108 retained, 36 healing bindings added.
- Four projectile and four beam profiles, plus holy/nature stationary healing.
- A single selected recipient may be the caster; mass healing supports 1–6 selected recipients.
- Light of the Protector explicitly anchors to the caster.
- No HP changes, resource consumption, rules, or concentration management.
- Visuals are broadcast only by the author of the completed-use message, once per message/activity.
- Original game assets and generated WebM are not stored in git.

Copy the scripts/ files into the canonical WoW_DnD5e_Source tree; media belongs
in that tree's visuals/ and is copied by rebuild.py. Do not install this folder
as a Foundry module. The complete source archive contains the bake reports,
36-binding audit, source hashes, rendering/framing scripts and release comparison.

Tests: `node visuals/test-visuals.mjs` from this directory. These use mocked API
objects; new effects still require a live Foundry 13 / dnd5e 5.3.3 check with Sequencer.
