const assert=require('node:assert/strict');
const {updateCryptVisuals}=require('../wowmap/update_crypt_visuals.js');
function setup() {
  const changes=[];
  function actor(id) {return {id,flags:{wowmap:{package:'void-crypt-dev2-r4',key:'wolf'}},system:{attributes:{hp:{value:7,max:38}}},
    items:[{id:'runtime-item',system:{identifier:'wolf-bite',uses:{spent:2},activities:{activity:{img:'old'}}}}],
    async update(data){changes.push({kind:'actor',id,data});},
    async updateEmbeddedDocuments(type,data){assert.equal(type,'Item');changes.push({kind:'items',id,data});}};}
  const world=actor('world'),synthetic=actor('synthetic');
  // Real Foundry activities are a collection; raw toObject yields the ID map.
  synthetic.items[0].toObject=()=>({system:{activities:{activity:{}}}});
  synthetic.items[0].system.activities={contents:[]};
  const token={actor:synthetic,actorLink:false,async update(data){changes.push({kind:'token',data});}};
  const env={game:{user:{isGM:true},actors:[world],scenes:[{tokens:[token]}]},fetch:async()=>({ok:true}),ui:{notifications:{info(){}}}};
  const image='wowmap/content/icons/new.webp';
  const bundle={format:'wowmap.foundry/1',mediaRoot:'wowmap/void-crypt-dev2-r4',visualRevision:'R4.1',actors:[{flags:world.flags,img:'wowmap/content/portraits/new.webp',prototypeToken:{texture:{src:'wowmap/content/tokens/new.webp'}},items:[{img:image,system:{identifier:'wolf-bite',activities:{activity:{img:image}}}}]}]};
  return {env,bundle,changes,world,synthetic};
}
(async()=>{
  const s=setup();assert.deepEqual(await updateCryptVisuals(s.env,s.bundle),{actors:1,tokens:1});
  assert.equal(s.world.system.attributes.hp.value,7);assert.equal(s.synthetic.system.attributes.hp.value,7);
  assert.equal(s.synthetic.items[0].system.uses.spent,2);
  for(const c of s.changes)for(const key of Object.keys(c.data))assert(!/hp|uses|effects|cryptState/.test(key));
  const syntheticItems=s.changes.find(c=>c.kind==='items'&&c.id==='synthetic').data[0];
  assert.equal(syntheticItems['system.activities.activity.img'],'wowmap/content/icons/new.webp');
  assert.equal(syntheticItems._id,'runtime-item');assert(!Object.hasOwn(syntheticItems,'system'));
  await updateCryptVisuals(s.env,s.bundle); // Repeat without creation or reset.
  const missing=setup();missing.env.fetch=async()=>({ok:false});await assert.rejects(()=>updateCryptVisuals(missing.env,missing.bundle),/недоступно/);assert.equal(missing.changes.length,0);
  const denied=setup();denied.env.game.user.isGM=false;await assert.rejects(()=>updateCryptVisuals(denied.env,denied.bundle),/мастеру/);assert.equal(denied.changes.length,0);
  console.log('Visual update passed: world and synthetic items, activities, missing media preflight, repeat run; HP/uses preserved. Mock API.');
})().catch(e=>{console.error(e);process.exitCode=1;});
