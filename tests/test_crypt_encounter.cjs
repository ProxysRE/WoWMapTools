const assert=require('node:assert/strict');
const {createCryptController}=require('../wowmap/crypt_encounter.js');
function setup(){
  let next=0;
  const actors=new Map();
  for(const [key,hp] of Object.entries({vaelis:150,echo:18,voidguard:85,rift:12})){
    const actor={name:key,system:{attributes:{hp:{value:hp,max:key==='vaelis'?300:hp}}},items:[],
      async getTokenDocument(data){return {toObject:()=>({...data,actorId:key,texture:{src:'token.webp'}})}}};actors.set(key,actor);
  }
  const tokens=[];tokens.get=id=>tokens.find(t=>t.id===id);
  function add(data){
    const token={...data,id:data.id||`token${++next}`,actor:structuredClone({system:actors.get(data.actorId).system}),
      async update(change){for(const [k,v] of Object.entries(change)){
        if(k==='flags.wowmap.cryptState')this.flags.wowmap.cryptState=structuredClone(v);
        else if(k==='texture.tint')this.texture={...this.texture,tint:v};
      }}};token.actor.items=[];tokens.push(token);return token;
  }
  const boss=add({id:'boss',actorId:'vaelis',x:1600,y:1360,width:1,height:1,flags:{wowmap:{}},texture:{}});
  const scene={id:'s',flags:{wowmap:{package:'p',key:'crypt-sanctum'}},tokens,grid:{size:80},
    async createEmbeddedDocuments(kind,docs){assert.equal(kind,'Token');return docs.map(add)},
    async deleteEmbeddedDocuments(kind,ids){for(const id of ids){const i=tokens.findIndex(t=>t.id===id);if(i>=0)tokens.splice(i,1)}}};
  const combat={round:1,scene:{id:'s'},combatant:{tokenId:'boss',initiative:15},combatants:[],
    async createEmbeddedDocuments(kind,docs){this.combatants.push(...docs);return docs}};
  const messages=[];const env={game:{user:{isGM:true},actors,combat},canvas:{scene},ui:{notifications:{info:()=>{}}},ChatMessage:{create:async x=>messages.push(x)}};
  const cfg={package:'p',actors:Object.fromEntries([...actors].map(([k])=>[k,k])),rifts:[[15,18],[27,18]],safePoints:{'1':[[[15,18],[14,18]],[[27,18],[28,18]]],'2':[[[15,18],[14,18]],[[27,18],[28,18]]]}};
  return {env,cfg,boss,scene,combat,run:createCryptController(env,cfg),messages};
}
(async()=>{
  const s=setup();
  s.boss.actor.system.attributes.hp.value=151;
  await assert.rejects(()=>s.run('phase'),/150/);
  s.boss.actor.system.attributes.hp.value=145;await s.run('phase');
  assert.equal(s.boss.actor.system.attributes.hp.value,145,'Phase change must not heal or clamp overflow');
  await assert.rejects(()=>s.run('phase'),/уже/);
  await s.run('warn');assert.equal(s.scene.tokens.length,3);
  assert.equal(s.scene.tokens[1].actorLink,false,'Portal hit points must be independent');
  await assert.rejects(()=>s.run('warn'),/предыдущую/);
  await assert.rejects(()=>s.run('tick'),/полный круг/);
  await s.run('close0');s.combat.round=2;await s.run('tick');
  const adds=s.scene.tokens.filter(t=>t.flags?.wowmap?.cryptSummon);
  assert.equal(adds.length,1,'Closed portal must not spawn its add');
  assert.equal(adds[0].actorLink,false);
  assert.equal(s.combat.combatants.length,0,'New summons must not act immediately');
  await s.run('tick');assert.equal(s.scene.tokens.filter(t=>t.flags?.wowmap?.cryptSummon).length,1,'No duplicate release');
  await assert.rejects(()=>s.run('warn'),/двух раундов/);
  s.combat.round=3;await s.run('tick');assert.equal(s.combat.combatants.length,1);
  await s.run('warn');
  s.scene.tokens.find(t=>t.flags?.wowmap?.cryptRift?.slot===1).actor.system.attributes.hp.value=0;
  s.combat.round=4;await s.run('tick');
  assert.equal(s.scene.tokens.filter(t=>t.flags?.wowmap?.cryptSummon).length,2,'Destroyed portal must not spawn');
  assert.equal(s.scene.tokens.filter(t=>t.actorId==='voidguard').length,1);
  await assert.rejects(()=>s.run('warn'),/Обе волны/);
  const blocked=setup();await blocked.run('phase');await blocked.run('warn');blocked.combat.round=2;
  blocked.scene.tokens.push({id:'pc',actorId:'pc',actor:{system:{attributes:{hp:{value:50}}}},x:900,y:1200,width:10,height:10,flags:{}});
  await assert.rejects(()=>blocked.run('tick'),/занято/);
  assert.equal(blocked.scene.tokens.filter(t=>t.flags?.wowmap?.cryptSummon).length,0,'Preflight all spawn positions before writing');
  blocked.boss.actor.system.attributes.hp.value=0;await assert.rejects(()=>blocked.run('tick'),/погиб/);
  const wrong=setup();wrong.env.game.user.isGM=false;await assert.rejects(()=>wrong.run('phase'),/мастеру/);
  console.log('Crypt encounter workflow passed: phase, portal closure, delayed turns, occupied slots, no duplicate waves. Mock API; no in-game verification.');
})().catch(e=>{console.error(e);process.exitCode=1});
