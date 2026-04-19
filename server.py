import os
from http.server import HTTPServer, SimpleHTTPRequestHandler
import threading

class DashboardHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/' or self.path == '/dashboard':
            self.path = '/dashboard.html'
        return SimpleHTTPRequestHandler.do_GET(self)
    def log_message(self, format, *args):
        pass

def run_server():
    port = int(os.environ.get('PORT', 8080))
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    httpd = HTTPServer(('0.0.0.0', port), DashboardHandler)
    httpd.serve_forever()

if __name__ == '__main__':
    run_server()
