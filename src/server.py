import socketserver
import ssl
import os
from typing import Callable, Optional

class DefaultHandler(socketserver.BaseRequestHandler):
    """Default handler that simply echos back received messages."""
    def handle(self):
        print(f"Client connected: {self.client_address[0]}:{self.client_address[1]}")
        try:
            while True:
                data = self.request.recv(1024)
                if not data:
                    break
                
                message = data.decode("utf-8", errors="ignore")
                print(f"Received: {message}")
                
                # Default behavior: Echo back
                response = f"Echo: {message}".encode("utf-8")
                self.request.sendall(response)
        except Exception as err:
            print(f"Connection error with {self.client_address[0]}: {err}")
        finally:
            print(f"Client disconnected: {self.client_address[0]}")


class SecureTCPServer(socketserver.TCPServer):
    """Custom TCPServer that wraps incoming sockets with TLS context."""
    def __init__(self, server_address, request_handler_class, ssl_context, bind_and_activate=True):
        self.ssl_context = ssl_context
        super().__init__(server_address, request_handler_class, bind_and_activate)

    def get_request(self):
        newsocket, fromaddr = self.socket.accept()
        connstream = self.ssl_context.wrap_socket(newsocket, server_side=True)
        return connstream, fromaddr


class SecureServerHelper:
    """Helper wrapper for configuring and managing an encrypted TCP server."""
    def __init__(
        self,
        cert_file: str = "server_cert.pem",
        key_file: str = "server_key.pem",
        host: str = "127.0.0.1",
        port: int = 8443,
        handler_cls: Optional[type] = None
    ):
        self.cert_file = cert_file
        self.key_file = key_file
        self.host = host
        self.port = port
        self.handler_cls = handler_cls or DefaultHandler
        self._server: Optional[SecureTCPServer] = None

    def _create_ssl_context(self) -> ssl.SSLContext:
        """Validates files and returns a configured TLS context."""
        if not (os.path.exists(self.cert_file) and os.path.exists(self.key_file)):
            raise FileNotFoundError(
                f"Missing TLS certificates. Could not find '{self.cert_file}' or '{self.key_file}'."
            )

        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        context.load_cert_chain(certfile=self.cert_file, keyfile=self.key_file)
        return context

    def start(self):
        """Initializes and runs the encrypted TCP server."""
        ssl_context = self._create_ssl_context()
        
        print(f"Starting Secure TCP Server at {self.host}:{self.port}...")
        self._server = SecureTCPServer(
            (self.host, self.port),
            self.handler_cls,
            ssl_context
        )
        
        try:
            self._server.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down server gracefully...")
        finally:
            self.stop()

    def stop(self):
        """Stops the server if running."""
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            print("Server stopped.")


if __name__ == "__main__":
    # Example usage: Quick start with default configurations
    server = SecureServerHelper(
        cert_file="server_cert.pem",
        key_file="server_key.pem",
        host="127.0.0.1",
        port=8443
    )
    
    server.start()