import threading
import server
import bot

if __name__ == '__main__':
    t = threading.Thread(target=server.run_server, daemon=True)
    t.start()
    bot.main()
