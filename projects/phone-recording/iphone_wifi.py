#!/usr/bin/env python3
"""Pinned Wi-Fi Blackmagic API. Only explicit record/stop writes; no USB fallback."""
import hashlib
import http.client
import json
import socket
import ssl
import sys
from iphone_api import HOST,PORT,CERT_SHA256


def request(path, method='GET'):
    if method != 'GET' and not (method == 'POST' and path in ('/control/api/v1/transports/0/record','/control/api/v1/transports/0/stop')):
        raise ValueError('Wi-Fi API mutation not allowlisted')
    if not path.startswith('/control/') or any(c in path for c in '\r\n'):
        raise ValueError('Only camera control read paths allowed')
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname=False;context.verify_mode=ssl.CERT_NONE
    connection=http.client.HTTPConnection(HOST,PORT,timeout=8)
    raw=socket.create_connection((HOST,PORT),timeout=8)
    try:
        connection.sock=context.wrap_socket(raw,server_hostname=HOST)
        digest=hashlib.sha256(connection.sock.getpeercert(binary_form=True)).hexdigest()
        if digest!=CERT_SHA256:raise ssl.SSLError('Camera certificate changed; no request sent')
        connection.request(method,path)
        response=connection.getresponse();body=response.read(1024*1024+1)
        if len(body)>1024*1024:raise ValueError('API response too large')
        return response.status,body.decode('utf-8')
    finally:
        connection.close();raw.close()


def read_json(path):
    code,body=request('/control/api/v1/'+path)
    if code!=200:raise RuntimeError(f'Camera read failed: HTTP {code}')
    return json.loads(body)


if __name__=='__main__':
    for path in sys.argv[1:] or ['/control/api/v1/transports/0/record']:
        status,body=request(path);print(path,'HTTP',status);print(body)
