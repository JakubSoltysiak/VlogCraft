"""Opt-in subprocess network guard used only by automated offline qualification."""
import errno
import ipaddress
import os
import socket

if os.environ.get('VLOGCRAFT_OFFLINE_TEST')=='1':
    log=os.environ.get('VLOGCRAFT_NETWORK_LOG')
    def record(message):
        if log:
            with open(log,'a',encoding='utf8') as file:file.write(message+'\n')
    def allowed(address):
        if not isinstance(address,tuple):return True
        host=address[0]
        if isinstance(host,bytes):host=host.decode('ascii')
        if host in ('localhost',None):return True
        try:return ipaddress.ip_address(str(host).split('%')[0]).is_loopback
        except ValueError:return False
    connect=socket.socket.connect;connect_ex=socket.socket.connect_ex;resolve=socket.getaddrinfo
    def local_connect(self,address):
        if not allowed(address):
            record('blocked external connect')
            raise PermissionError('Offline qualification blocks external sockets')
        return connect(self,address)
    def local_connect_ex(self,address):
        if not allowed(address):
            record('blocked external connect_ex')
            return errno.ENETUNREACH
        return connect_ex(self,address)
    def local_resolve(host,*args,**kwargs):
        if not allowed((host,0)):
            record('blocked external resolution')
            raise PermissionError('Offline qualification blocks external resolution')
        return resolve(host,*args,**kwargs)
    socket.socket.connect=local_connect;socket.socket.connect_ex=local_connect_ex;socket.getaddrinfo=local_resolve
    try:
        socket.create_connection(('192.0.2.1',443),timeout=.1)
        raise RuntimeError('Offline socket guard failed')
    except PermissionError:record('guard active')
