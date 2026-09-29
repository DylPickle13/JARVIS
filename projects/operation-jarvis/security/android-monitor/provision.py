#!/usr/bin/env python3
"""One-time private provisioning. Refuses to overwrite an existing installation."""
import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import secrets
import ssl
import subprocess


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--host', required=True, help='Mac home-LAN IPv4 address (reserve in DHCP)')
    p.add_argument('--private-dir', type=Path, required=True)
    p.add_argument('--java-home', type=Path, required=True)
    args = p.parse_args()
    ip = ipaddress.IPv4Address(args.host)
    if not ip.is_private or ip.is_loopback or ip.is_link_local:
        raise SystemExit('Use a private LAN address.')
    root = args.private_dir.resolve()
    source = Path(__file__).resolve().parent
    if root == source or source in root.parents:
        raise SystemExit('Private state must be outside source.')
    os.umask(0o077)
    root.mkdir(parents=True, exist_ok=False)
    token = secrets.token_urlsafe(32)
    password = secrets.token_urlsafe(32)
    (root/'signing-password').write_text(password + '\n')
    (root/'openssl.cnf').write_text('[req]\ndistinguished_name=dn\nx509_extensions=ext\nprompt=no\n'
        '[dn]\nCN=JARVIS Android Monitor\n[ext]\nbasicConstraints=critical,CA:FALSE\n'
        'keyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n'
        f'subjectAltName=IP:{ip}\n')
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '825',
        '-config', str(root/'openssl.cnf'), '-keyout', str(root/'server.key'), '-out', str(root/'server.crt')],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    der = ssl.PEM_cert_to_DER_cert((root/'server.crt').read_text())
    (root/'server.json').write_text(json.dumps({'bind': str(ip), 'port': 8794, 'token': token}))
    (root/'client.json').write_text(json.dumps({'url': f'https://{ip}:8794/v1/presence',
        'certificateSha256': hashlib.sha256(der).hexdigest(), 'token': token}))
    subprocess.run([str(args.java_home/'bin/keytool'), '-genkeypair', '-keystore', str(root/'signing.p12'),
        '-storetype', 'PKCS12', '-storepass:file', str(root/'signing-password'), '-alias', 'monitor',
        '-keyalg', 'RSA', '-keysize', '2048', '-validity', '3650', '-dname', 'CN=JARVIS Monitor Local'],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print('Private provisioning created. No secrets printed.')


if __name__ == '__main__': main()
