import subprocess, time, requests, sys
print('Starting Uvicorn...')
server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000'], cwd='backend')
time.sleep(15)
print('Testing direct request...')
try:
    res = requests.post('http://127.0.0.1:8000/api/auth/login', json={'username': 'admin', 'password': 'admin123'}, timeout=10)
    print('Direct request json:', res.status_code, res.text)
    res2 = requests.post('http://127.0.0.1:8000/api/auth/login', data={'username': 'admin', 'password': 'admin123'}, timeout=10)
    print('Direct request data:', res2.status_code, res2.text)
except Exception as e:
    print('Direct request failed:', e)
finally:
    server.terminate()
