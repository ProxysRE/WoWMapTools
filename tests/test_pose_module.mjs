import assert from 'node:assert/strict';
import {setPose,togglePose,variantsFor,renderHUD} from '../foundry_modules/wowmap-poses/poses.mjs';

globalThis.Image=class {
  set src(value) { queueMicrotask(() => value==='missing.webp' ? this.onerror() : this.onload()); }
};

function token({linked=false}={}) {
  const variants={normal:{token:'idle.webp',portrait:'idle-portrait.webp'},combat:{token:'combat.webp',portrait:'combat-portrait.webp'}};
  const actor={isOwner:true,img:'idle-portrait.webp',updates:[],getFlag:()=>variants,
    async update(patch) { this.updates.push(patch);this.img=patch.img; }};
  const document={isOwner:true,actorLink:linked,actor,texture:{src:'idle.webp'},state:'normal',updates:[],
    getFlag(scope,key) { return key==='pose' ? this.state : undefined; },
    async update(patch) { this.updates.push(patch);this.texture.src=patch['texture.src'];this.state=patch['flags.wowmap.pose']; }};
  return {document,variants};
}

// Both images switch; no changes to HP, inventory, effects, token transform or prototype.
for (const linked of [false,true]) {
  const {document}=token({linked});
  await setPose(document,'combat');assert.equal(document.texture.src,'combat.webp');assert.equal(document.actor.img,'combat-portrait.webp');
  assert.deepEqual(Object.keys(document.updates[0]).sort(),['flags.wowmap.pose','texture.src']);
  assert.deepEqual(document.actor.updates,[{img:'combat-portrait.webp'}]);
  await togglePose({document});assert.equal(document.state,'normal');assert.equal(document.actor.img,'idle-portrait.webp');
}
// Rapid double click returns to the starting state, rather than both calls choosing combat.
{
  const {document}=token();await Promise.all([togglePose(document),togglePose(document)]);assert.equal(document.state,'normal');
}
// Unlinked copies have independent synthetic actors and remain independent.
{
  const a=token(),b=token();await setPose(a.document,'combat');assert.equal(b.document.actor.img,'idle-portrait.webp');
}
// Missing files, invalid input and permissions fail before any mutation.
for (const failure of ['token-permission','actor-permission','missing-file','invalid-state','missing-variants']) {
  const {document,variants}=token();
  if (failure==='token-permission') document.isOwner=false;
  if (failure==='actor-permission') document.actor.isOwner=false;
  if (failure==='missing-file') variants.combat.portrait='missing.webp';
  if (failure==='missing-variants') document.actor.getFlag=()=>null;
  await assert.rejects(setPose(document,failure==='invalid-state'?'nope':'combat'));
  assert.equal(document.updates.length,0);assert.equal(document.actor.updates.length,0);
}
// A portrait update failure restores the token; a later request still succeeds.
{
  const {document}=token();const update=document.actor.update;
  document.actor.update=async()=>{throw new Error('portrait rejected');};
  await assert.rejects(setPose(document,'combat'),/portrait rejected/);assert.equal(document.texture.src,'idle.webp');assert.equal(document.state,'normal');
  document.actor.update=update;await setPose(document,'combat');assert.equal(document.state,'combat');
}
// Token-local variants override actor defaults; an omitted portrait is supported.
{
  const {document}=token();const local={normal:{token:'a.webp'},combat:{token:'b.webp'}};
  document.getFlag=(scope,key)=>key==='poseVariants'?local:'normal';
  assert.equal(variantsFor(document),local);await setPose(document,'combat');assert.equal(document.texture.src,'b.webp');assert.equal(document.actor.updates.length,0);
}
// Minimal native DOM verifies V13 HTMLElement handling and duplicate prevention.
globalThis.HTMLElement=class {};
{
  const {document}=token();let button=null;
  const root=new HTMLElement();root.querySelector=selector=>selector==='.wowmap-pose-toggle'?button:{append:b=>{button=b;}};
  globalThis.window={document:{createElement:()=>({setAttribute(){},addEventListener(){}})}};
  renderHUD({object:{document}},root);assert.ok(button);assert.equal(button.type,'button');
  const first=button;renderHUD({object:{document}},root);assert.equal(button,first);
}
console.log('Pose module checks passed (mock Foundry 13 API and DOM; no in-game verification)');
