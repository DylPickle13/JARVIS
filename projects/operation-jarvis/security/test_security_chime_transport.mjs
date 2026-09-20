// Offline synthetic peer: never connects to a chime or emits sound.
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import http from 'node:http';
import {EventEmitter} from 'node:events';
import TpapSession, {localPost} from './security_chime_transport.mjs';
import {p256} from './private-notes/chime-tpap-v2/node_modules/@noble/curves/nist.js';
const P=p256.Point,O=P.Fn.ORDER;
const M=P.fromHex('02886e2f97ace46e55ba9dd7242579f2993b64e16ef3dcab95afd497333d8fa12f');
const N=P.fromHex('03d8bbd6c639c62937b04d997f38c3770719c629d7014d49a24b4f98baa1292b49');
const sha=b=>crypto.createHash('sha256').update(b).digest();
const enc=p=>Buffer.from(p.toBytes(false));
const pref=b=>{const n=Buffer.alloc(8);n.writeBigUInt64LE(BigInt(b.length));return Buffer.concat([n,b]);};
const hk=(key,salt,info,len)=>Buffer.from(crypto.hkdfSync('sha256',key,salt,info,len));
function peer(options={}){
 const password='synthetic-test-password';
 const salt=Buffer.alloc(16,4),devRandom=Buffer.alloc(32,5),y=19n;
 const material=crypto.pbkdf2Sync(crypto.createHash('sha1').update(password).digest('hex'),salt,3000,80,'sha256');
 const w0=BigInt('0x'+material.subarray(0,40).toString('hex'))%O;
 const w1=BigInt('0x'+material.subarray(40).toString('hex'))%O;
 const R=P.BASE.multiply(y).add(N.multiply(w0));
 let userRandom,key,baseNonce,calls=0,queries=[];
 const request=async(host,path,body,binary)=>{
  calls++;assert.equal(host,'192.168.255.254');
  if(!binary && body.params.sub_method==='pake_register'){
   userRandom=Buffer.from(body.params.user_random,'base64');
   return {error_code:0,result:{dev_random:devRandom.toString('base64'),dev_salt:salt.toString('base64'),dev_share:enc(R).toString('base64'),
    iterations:3000,cipher_suites:1,encryption:'aes_128_ccm',extra_crypt:{type:'password_shadow',params:{passwd_id:2}},...options.register}};
  }
  if(!binary && body.params.sub_method==='pake_share'){
   const L=P.fromBytes(Buffer.from(body.params.user_share,'base64'));
   const Z=L.subtract(M.multiply(w0)).multiply(y),V=P.BASE.multiply(w1).multiply(y);
   let hex=w0.toString(16);if(hex.length%2)hex='0'+hex;
   let w=Buffer.from(hex,'hex');if(w.length%2&&w[0]&128)w=Buffer.concat([Buffer.from([0]),w]);
   const hash=sha(Buffer.concat([sha(Buffer.concat([Buffer.from('PAKE V1'),userRandom,devRandom])),Buffer.alloc(0),Buffer.alloc(0),
    enc(M),enc(N),enc(L),enc(R),enc(Z),enc(V),w].map(pref)));
   const confirms=hk(hash,Buffer.alloc(64),'ConfirmationKeys',64),shared=hk(hash,Buffer.alloc(32),'SharedKey',32);
   assert.deepEqual(Buffer.from(body.params.user_confirm,'base64'),crypto.createHmac('sha256',confirms.subarray(0,32)).update(enc(R)).digest());
   const proof=crypto.createHmac('sha256',confirms.subarray(32)).update(enc(L)).digest();
   if(options.badProof)proof[0]^=1;
   key=hk(shared,Buffer.from('tp-kdf-salt-aes128-key'),Buffer.from('tp-kdf-info-aes128-key'),16);
   baseNonce=hk(shared,Buffer.from('tp-kdf-salt-aes128-iv'),Buffer.from('tp-kdf-info-aes128-iv'),12);
   return {error_code:0,result:{dev_confirm:proof.toString('base64'),sessionId:'synthetic-token',start_seq:23}};
  }
  assert.equal(path,'/stok=synthetic-token/ds');
  const seq=body.readUInt32BE(0),nonce=Buffer.from(baseNonce);nonce.writeUInt32BE(seq,8);
  const d=crypto.createDecipheriv('aes-128-ccm',key,nonce,{authTagLength:16});
  d.setAuthTag(body.subarray(-16));d.setAAD(Buffer.alloc(0),{plaintextLength:body.length-20});
  const query=JSON.parse(Buffer.concat([d.update(body.subarray(4,-16)),d.final()]));queries.push(query.method);
  const plain=Buffer.from(JSON.stringify({error_code:0,result:{model:'D100C',echo:query.method}}));
  const c=crypto.createCipheriv('aes-128-ccm',key,nonce,{authTagLength:16});c.setAAD(Buffer.alloc(0),{plaintextLength:plain.length});
  const result=Buffer.concat([body.subarray(0,4),c.update(plain),c.final(),c.getAuthTag()]);
  if(options.tamper)result[result.length-1]^=1;
  if(options.wrongSequence)result.writeUInt32BE(seq+1);
  return result;
 };
 return {session:new TpapSession({host:'192.168.255.254',password,request}),calls:()=>calls,queries};
}
let checks=0;
{
 const p=peer();await p.session.handshake();
 assert.equal((await p.session.query('get_device_info')).model,'D100C');
 assert.deepEqual(p.queries,['get_device_info']);
 await assert.rejects(p.session.query('set_volume'));assert.equal(p.calls(),3);
 await assert.rejects(p.session.handshake());assert.equal(p.calls(),3);
 p.session.close();await assert.rejects(p.session.query('get_device_info'));checks++;
}
for(const register of [{iterations:100001},{iterations:0},{cipher_suites:2},{encryption:'chacha20_poly1305'},
 {dev_share:Buffer.alloc(65).toString('base64')},{dev_salt:'invalid!'},{extra_crypt:{type:'unknown'}},
 {extra_crypt:{type:'password_shadow',params:{passwd_id:5}}}]){
 const p=peer({register});await assert.rejects(p.session.handshake());assert.equal(p.calls(),1);checks++;
}
{
 const p=peer({badProof:true});await assert.rejects(p.session.handshake(),/device_proof_failed/);
 await assert.rejects(p.session.query('get_device_info'));assert.equal(p.calls(),2);checks++;
}
for(const options of [{tamper:true},{wrongSequence:true}]){
 const p=peer(options);await p.session.handshake();await assert.rejects(p.session.query('get_device_info'));
 assert.equal(p.calls(),3);p.session.close();checks++;
}
{
 const p=peer();await p.session.handshake();
 for(let i=0;i<4;i++)await p.session.query('get_device_info');
 await assert.rejects(p.session.query('get_device_info'));assert.equal(p.calls(),6);p.session.close();checks++;
}
assert.throws(()=>new TpapSession({host:'example.com',password:'synthetic'}));checks++;
{
 const original=http.request;
 try {
  for(const mode of ['redirect','oversize','valid']){
   http.request=(options,callback)=>{
    assert.equal(options.hostname,'192.168.255.254');assert.equal(options.agent,false);
    const req=new EventEmitter();req.destroy=()=>{};
    req.end=()=>queueMicrotask(()=>{
     const res=new EventEmitter();res.statusCode=mode==='redirect'?302:200;res.destroy=()=>{};
     callback(res);
     if(mode!=='redirect'){
      res.emit('data',mode==='oversize'?Buffer.alloc(65537):Buffer.from('{"ok":true}'));
      res.emit('end');
     }
    });
    return req;
   };
   if(mode==='valid')assert.deepEqual(await localPost('192.168.255.254','/',{}),{ok:true});
   else await assert.rejects(localPost('192.168.255.254','/',{}));
   checks++;
  }
 }finally{http.request=original;}
}
assert.throws(()=>localPost('192.168.255.254','/arbitrary',{}));checks++;
console.log(JSON.stringify({offline_transport_checks:checks,network_access:false}));
