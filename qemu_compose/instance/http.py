import threading
from functools import partial
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

class HttpServer:
    def __init__(self, listen:str, port:int, root:str):
        self.listen = listen
        self.port = port
        self.root = root

    def start(self):
        http_handler = partial(SimpleHTTPRequestHandler, directory=self.root)
        server = ThreadingHTTPServer((self.listen, self.port), http_handler)
        server_thread = threading.Thread(target=server.serve_forever)
        server_thread.daemon = True
        server_thread.start()
