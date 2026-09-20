// Narrow D100C TPAP/PAKE-2 transport, based on the verified TPAP exchange.
// Reference: ioBroker.tapo 30dc64a55354694fe524bb1bd2ad42c64ad80206.
// Only P-256/SHA256/AES128-CCM and the observed password_shadow/2 transform.
import crypto from 'node:crypto';
import http from 'node:http';
import net from 'node:net';
import {p256} from './private-notes/chime-tpap-v2/node_modules/@noble/curves/nist.js';

const Point=p256.Point, ORDER=Point.Fn.ORDER;
const M=Point.fromHex('02886e2f97ace46e55ba9dd7242579f2993b64e16ef3dcab95afd497333d8fa12f');
const N=Point.fromHex('03d8bbd6c639c62937b04d997f38c3770719c629d7014d49a24b4f98baa1292b49');
const METHODS=new Set(['get_device_info','component_nego','get_support_alarm_type_list',
 'get_alarm_configure','play_alarm','stop_alarm']);
const fail=()=>{throw new Error('chime_protocol_validation_failed');};
const sha=b=>crypto.createHash('sha256').update(b).digest();
const number=b=>BigInt('0x'+b.toString('hex'));
const pointBytes=p=>Buffer.from(p.toBytes(false));
function lengthPrefix(b){const n=Buffer.alloc(8);n.writeBigUInt64LE(BigInt(b.length));return Buffer.concat([n,b]);}
function encodedScalar(w){
 let hex=w.toString(16);if(hex.length%2)hex='0'+hex;
 const b=Buffer.from(hex,'hex');
 return b.length%2 && b[0]&128?Buffer.concat([Buffer.from([0]),b]):b;
}
function expand(label,hash,len){return Buffer.from(crypto.hkdfSync('sha256',hash,Buffer.alloc(len),label,len));}
function derive(shared,salt,info,len){return Buffer.from(crypto.hkdfSync('sha256',shared,Buffer.from(salt),Buffer.from(info),len));}
function base64(value,min,max){
 if(typeof value!=='string'||value.length>max*2||!/^[A-Za-z0-9+/]*={0,2}$/.test(value))fail();
 const b=Buffer.from(value,'base64');if(b.length<min||b.length>max||b.toString('base64')!==value)fail();return b;
}

// No proxy, redirects, ambient auth, retries, DNS lookup or persistent agent.
export function localPost(host,path,body,binary=false){
 if(net.isIP(host)!==4||!host.startsWith('192.168.') ||
    !(path==='/'||/^\/stok=[A-Za-z0-9_-]{1,256}\/ds$/.test(path)))fail();
 const data=Buffer.isBuffer(body)?body:Buffer.from(JSON.stringify(body));
 if(data.length>65536)fail();
 return new Promise((resolve,reject)=>{
  let settled=false;
  const finish=(error,value)=>{if(settled)return;settled=true;clearTimeout(timer);error?reject(error):resolve(value);};
  const req=http.request({hostname:host,port:80,path,method:'POST',agent:false,
   headers:{'Content-Type':binary?'application/octet-stream':'application/json; charset=UTF-8',
    'Accept':binary?'application/octet-stream':'application/json','Content-Length':data.length,'Connection':'close'}},res=>{
   if(res.statusCode!==200){res.destroy();finish(new Error('chime_http_failed'));return;}
   const chunks=[];let bytes=0;
   res.on('data',chunk=>{bytes+=chunk.length;if(bytes>65536){res.destroy();finish(new Error('chime_response_too_large'));}else chunks.push(chunk);});
   res.on('error',()=>finish(new Error('chime_http_failed')));
   res.on('aborted',()=>finish(new Error('chime_http_failed')));
   res.on('end',()=>{try{const b=Buffer.concat(chunks);finish(null,binary?b:JSON.parse(b.toString('utf8')));}catch{finish(new Error('chime_invalid_response'));}});
  });
  const timer=setTimeout(()=>{req.destroy();finish(new Error('chime_timeout'));},5000);
  req.on('error',()=>finish(new Error('chime_http_failed')));
  req.end(data);
 });
}

export default class TpapSession {
 #host;#password;#request;#random;#key;#nonce;#seq;#token;#attempted=false;#requests=0;#max;
 constructor({host,password,maxRequests=6,request=localPost,random=crypto.randomBytes}){
  if(net.isIP(host)!==4||!host.startsWith('192.168.')||typeof password!=='string'||!password||
     !Number.isInteger(maxRequests)||maxRequests<3||maxRequests>7)fail();
  this.#host=host;this.#password=password;this.#request=request;this.#random=random;this.#max=maxRequests;
 }
 async #post(path,body,binary=false){if(++this.#requests>this.#max)fail();return this.#request(this.#host,path,body,binary);}
 async handshake(){
  if(this.#attempted)fail();this.#attempted=true;
  try {
   const userRandom=this.#random(32);
   const register=await this.#post('/',{method:'login',params:{sub_method:'pake_register',
    username:crypto.createHash('md5').update('admin').digest('hex'),
    user_random:userRandom.toString('base64'),cipher_suites:[1],encryption:['aes_128_ccm'],passcode_type:'userpw',stok:null}});
   if(register?.error_code!==0)throw new Error('chime_authentication_failed');
   const r=register.result;
   if(!r||r.cipher_suites!==1||r.encryption!=='aes_128_ccm'||
      !Number.isInteger(r.iterations)||r.iterations<1||r.iterations>100000||
      r.extra_crypt?.type!=='password_shadow'||String(r.extra_crypt.params?.passwd_id)!=='2')fail();
   const devRandom=base64(r.dev_random,32,32),salt=base64(r.dev_salt,8,64);
   const R=Point.fromBytes(base64(r.dev_share,65,65));R.assertValidity();if(R.is0())fail();
   const credential=crypto.createHash('sha1').update(this.#password).digest('hex');
   const material=crypto.pbkdf2Sync(credential,salt,r.iterations,80,'sha256');
   const w0=number(material.subarray(0,40))%ORDER,w1=number(material.subarray(40))%ORDER;
   material.fill(0);if(w0===0n||w1===0n)fail();
   let x;let tries=0;do{if(++tries>128)fail();x=number(this.#random(32));}while(x===0n||x>=ORDER);
   const L=Point.BASE.multiply(x).add(M.multiply(w0));
   const prime=R.subtract(N.multiply(w0));if(L.is0()||prime.is0())fail();
   const le=pointBytes(L),re=pointBytes(R);
   const transcript=sha(Buffer.concat([
    sha(Buffer.concat([Buffer.from('PAKE V1'),userRandom,devRandom])),Buffer.alloc(0),Buffer.alloc(0),
    pointBytes(M),pointBytes(N),le,re,pointBytes(prime.multiply(x)),pointBytes(prime.multiply(w1)),encodedScalar(w0)
   ].map(lengthPrefix)));
   const confirms=expand('ConfirmationKeys',transcript,64),shared=expand('SharedKey',transcript,32);
   const userConfirm=crypto.createHmac('sha256',confirms.subarray(0,32)).update(re).digest();
   const expected=crypto.createHmac('sha256',confirms.subarray(32)).update(le).digest();
   const share=await this.#post('/',{method:'login',params:{sub_method:'pake_share',user_share:le.toString('base64'),user_confirm:userConfirm.toString('base64')}});
   if(share?.error_code!==0)throw new Error('chime_authentication_failed');
   const s=share.result,proof=base64(s?.dev_confirm,32,32);
   if(!crypto.timingSafeEqual(proof,expected))throw new Error('device_proof_failed');
   const token=s.sessionId||s.stok;
   const seq=typeof s.start_seq==='string'&&/^\d{1,10}$/.test(s.start_seq)?Number(s.start_seq):s.start_seq;
   if(typeof token!=='string'||!/^[A-Za-z0-9_-]{1,256}$/.test(token)||!Number.isInteger(seq)||seq<0||seq>=0xffffffff)fail();
   this.#key=derive(shared,'tp-kdf-salt-aes128-key','tp-kdf-info-aes128-key',16);
   this.#nonce=derive(shared,'tp-kdf-salt-aes128-iv','tp-kdf-info-aes128-iv',12);
   this.#seq=seq;this.#token=token;confirms.fill(0);shared.fill(0);
  } finally {this.#password='';}
 }
 async query(method,params={}){
  if(!this.#key||!METHODS.has(method)||this.#seq>=0xffffffff)fail();
  const seq=this.#seq++,nonce=Buffer.from(this.#nonce);nonce.writeUInt32BE(seq,8);
  const plain=Buffer.from(JSON.stringify({method,params,requestTimeMils:Date.now(),terminalUUID:crypto.randomUUID()}));
  const cipher=crypto.createCipheriv('aes-128-ccm',this.#key,nonce,{authTagLength:16});
  cipher.setAAD(Buffer.alloc(0),{plaintextLength:plain.length});
  const head=Buffer.alloc(4);head.writeUInt32BE(seq);
  const wire=Buffer.concat([head,cipher.update(plain),cipher.final(),cipher.getAuthTag()]);plain.fill(0);
  const response=await this.#post(`/stok=${this.#token}/ds`,wire,true);
  if(!Buffer.isBuffer(response)||response.length<20||response.length>65536||response.readUInt32BE(0)!==seq)fail();
  const decipher=crypto.createDecipheriv('aes-128-ccm',this.#key,nonce,{authTagLength:16});
  decipher.setAuthTag(response.subarray(-16));decipher.setAAD(Buffer.alloc(0),{plaintextLength:response.length-20});
  const decoded=Buffer.concat([decipher.update(response.subarray(4,-16)),decipher.final()]);
  let result;try{result=JSON.parse(decoded.toString('utf8'));}finally{decoded.fill(0);}
  if(result?.error_code!==0)throw new Error('chime_request_rejected');return result.result;
 }
 close(){this.#key?.fill(0);this.#nonce?.fill(0);this.#key=undefined;this.#nonce=undefined;this.#token='';this.#password='';}
}
