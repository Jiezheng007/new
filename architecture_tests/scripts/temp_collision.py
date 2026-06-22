import requests, time, threading
def poke():
    for _ in range(50):
        try:
            requests.post("http://127.0.0.1:8000/api/import/demo", timeout=2)
        except:
            pass
        time.sleep(1)
threads = [threading.Thread(target=poke) for _ in range(2)]
for t in threads: t.start()
