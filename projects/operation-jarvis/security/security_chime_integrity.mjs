// Pin the isolated runtime tree, not just the transport source file.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

export function runtimeDigest(root) {
 const hash=crypto.createHash('sha256');
 function walk(dir,rel='') {
  if(!fs.lstatSync(dir).isDirectory()) throw new Error('chime_transport_integrity_failed');
  for(const name of fs.readdirSync(dir).sort()) {
   if(name==='.bin') continue; // CLI links are never used by the worker.
   const full=path.join(dir,name),key=path.posix.join(rel,name),stat=fs.lstatSync(full);
   if(stat.isSymbolicLink()) throw new Error('chime_transport_integrity_failed');
   if(stat.isDirectory()) walk(full,key);
   else if(stat.isFile()) {
    hash.update(key+'\0');
    hash.update(crypto.createHash('sha256').update(fs.readFileSync(full)).digest());
   } else throw new Error('chime_transport_integrity_failed');
  }
 }
 walk(root);
 return hash.digest('hex');
}
