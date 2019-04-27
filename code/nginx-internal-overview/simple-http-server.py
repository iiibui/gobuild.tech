#-*- coding:utf-8 -*-
# python3 simple-http-server.py
import socket

server_address = ('127.0.0.1', 80)
server_socket = socket.socket(family=socket.AF_INET, type=socket.SOCK_STREAM)
server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR  , True) # 避免测试时发生 Address already in use 错误
server_socket.bind(server_address)
server_socket.listen(8)
print('serving http://%s:%d' % server_address)
while True:
    client_socket, client_address = server_socket.accept()
    print('client', client_address, 'connected')
    data = client_socket.recv(1024)
    if not data:
        print('client', client_address, 'maybe close')
        client_socket.close()
        continue
    print('client', client_address, 'send:')
    print(data)
    client_socket.send(b'HTTP/1.1 200 OK\r\n') # 状态行
    client_socket.send(b'Connection: Close\r\n') # 响应头
    client_socket.send(b'\r\n') # 响应头结束
    client_socket.send(b'<h1>It works!</h1>') # 响应体
    client_socket.close()