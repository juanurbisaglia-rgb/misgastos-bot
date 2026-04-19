import os
from http.server import HTTPServer, SimpleHTTPRequestHandler

class DashboardHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/' or self.path == '/dashboard':
            self.path = '/dashboard.html'
        return SimpleHTTPRequestHandler.do_GET(self)
    def log_message(self, format, *args):
        pass

def run_server():
    port = int(os.environ.get('PORT', 8080))
    os.chdir('/app')
    httpd = HTTPServer(('0.0.0.0', port), DashboardHandler)
    print(f"Dashboard corriendo en puerto {port}")
    httpd.serve_forever()

if __name__ == '__main__':
    run_server()
