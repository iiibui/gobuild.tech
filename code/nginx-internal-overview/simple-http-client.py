#-*- coding:utf-8 -*-
# python3 simple-http-client.py
import socket

client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server_address = ('185.199.111.153', 80) # 可域名直连，但python解析到的ip可能连不上
client.connect(server_address)
client.send(b'GET / HTTP/1.1\r\n')
client.send(b'Host: gobuild.tech\r\n')
client.send(b'\r\n')

print('recv:')
print(client.recv(1024))