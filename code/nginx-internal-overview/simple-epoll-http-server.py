#-*- coding:utf-8 -*-
# python3 simple-epoll-http-server.py
import socket
import select

server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, True)
server_socket.bind(("127.0.0.1", 8888))
server_socket.listen(10)
server_socket.setblocking(False)

#创建epoll事件对象，后续要监控的事件添加到其中
epoll = select.epoll()
#注册服务器监听fd到等待读事件集合，server_socket是用来accept新连接的，不能读/写数据
epoll.register(server_socket.fileno(), select.EPOLLIN)
#用于关联事件和socket对象；和C语言不同，注册事件时不能关联上下文
fd_to_socket = {server_socket.fileno(): server_socket, }

while True:
  print("waiting connection active......")
  #轮询注册的事件集合，返回值为[(文件句柄，对应的事件)，(...),....]
  events = epoll.poll(-1)  # 永不超时
  if not events:
     print("epoll.poll error")
     break

  for fd, event in events:
      #如果活动socket为当前服务器socket，表示有新连接
    if fd == server_socket.fileno():
         connection, client_address = server_socket.accept()
         print(client_address, 'connected')
         connection.setblocking(False)
         client_fd = connection.fileno()
         fd_to_socket[client_fd] = connection
         epoll.register(client_fd, select.EPOLLIN)  # 只添加读事件
         continue

    connection = fd_to_socket[fd]
    close_reason = 'close because of network event'
    if event & select.EPOLLIN:  # 可读事件
        print(connection.getpeername(), 'can read')
        data = connection.recv(1024)
        if data:
           print(connection.getpeername(), 'send:')
           print(data)
           epoll.modify(fd, select.EPOLLOUT)
           continue
        #else: # 关闭
        close_reason = 'close because of recv error'
    if event & select.EPOLLOUT:  # 可写事件
        print(connection.getpeername(), 'can write')
        #发送响应数据
        connection.send(b'HTTP/1.1 200 OK\r\n')
        connection.send(b'Connection: close\r\n')
        connection.send(b'\r\n')
        connection.send(b'<h1>It Works!</h1>')
        # 数据可能只写到操作系统的缓冲区，后面的close调用会尝试把数据发送到网络
        close_reason = 'close after send response data'

    #if event & select.EPOLLHUP:  # 关闭事件
    print(connection.getpeername(), close_reason)
    epoll.unregister(fd)
    connection.close()
    del fd_to_socket[fd]

epoll.unregister(server_socket.fileno())
epoll.close()
server_socket.close()