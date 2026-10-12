FastAPI Logs Viewer: Setup and Run Guide
Oct 12, 2026 · @Gaurish rane
Run the standalone project first (sections 2 and 3, about 15 minutes), then copy it into YCC (section 4). All commands are for Windows Command Prompt, starting from D:\Server\mastek\fastapi-logs-list.
1. Install these first
Tool
Version
Check with
Notes
Python
3.10 or newer
python --version
YCC already uses 3.10.8
Node.js
18.19+ or 20.x
node --version
Needed for the Angular UI (Angular 17.3)
MongoDB
6.0 or newer
see below
Local install, Docker, or a hosted URL such as MongoDB Atlas
For MongoDB, pick one:
• You already have a URL: use it in step 2.3 and skip the rest of this list.
• Local install: install MongoDB Community Server from mongodb.com with the "Run as a Windows service" option. Its URL is mongodb://localhost:27017.
• Docker: docker run -d --name mongo -p 27017:27017 mongo:7. Same URL as above.
2. Run the backend
The backend is a small demo FastAPI app with log capture switched on. It records every request into MongoDB and serves the logs API.
1. Open a terminal in the backend folder and create a virtual environment:
   cd D:\Server\mastek\fastapi-logs-list\backend
   python -m venv .venv
   .venv\Scripts\activate
   In PowerShell, use .venv\Scripts\Activate.ps1 instead.
2. Install the packages:
   pip install -r requirements-dev.txt
3. Create your settings file and put in the MongoDB URL:
   copy .env.example .env
   notepad .env
   Change LOGS_MONGODB_URL= to your URL. Leave it as mongodb://localhost:27017 for a local MongoDB. The other values can stay as they are.
4. Start the server:
   uvicorn app.main:app --reload --port 8000
   Always start it from the backend folder so it finds .env. If MongoDB is unreachable you will see "Could not reach logs MongoDB at startup"; fix the URL and restart.
5. Fill the database with sample logs so the UI has something to show. In a second terminal (activate .venv again first):
   python -m app.seed --count 2000 --hours 48
6. Create a few real logs by opening these in the browser: http://localhost:8000/items/5, http://localhost:8000/items/500 (a 404 warning), http://localhost:8000/error (a 500 error).
7. Check the API answers: open http://localhost:8000/api/logs?range=1h. You should see JSON with an items list. The full API is browsable at http://localhost:8000/docs.
Optional: run the automated tests with pytest. They use a fake in-memory MongoDB, so they pass without a server.
3. Run the logs UI
Keep the backend running from section 2, then in a new terminal:
1. Install and start the Angular app:
   cd D:\Server\mastek\fastapi-logs-list\frontend
   npm install
   npm start
   The first npm install takes a few minutes. npm start forwards every /api call to the backend on port 8000, so nothing else needs configuring.
2. Open http://localhost:4200/logs.
3. Try it out:
    ◦ Change Timeline to "Last 24 hours" to see all the sample data.
    ◦ Tick Error under Contains Console Level to see only failing requests.
    ◦ Type in Search logs... to search paths and messages.
    ◦ Click a row to open its details on the right. Press Esc to close it.
    ◦ Press Live, then open http://localhost:8000/items/7 in another tab. The new request appears at the top within about 2 seconds.
    ◦ Use the download button for a JSON or CSV file of what is on screen.
The address bar keeps your filters (for example /logs?range=24h&level=error), so you can bookmark or share a filtered view.
4. Add it to YCC
Once the standalone version works, copy two folders into YCC and add a few lines of code. Nothing in YCC needs upgrading: this was tested on YCC's Python 3.10, FastAPI 0.100 and pydantic-settings 2.5.
Backend: YCCInnovationPython
1. Install pymongo in YCC's virtual environment and add pymongo>=4.13 to requirements.txt:
   cd D:\Server\mastek\YCCInnovationPython
   venv\Scripts\activate
   pip install "pymongo>=4.13"
2. Copy the folder fastapi-logs-list\backend\app\logs_viewer into YCCInnovationPython\backend\app\app\ so it sits next to main.py.
3. Copy fastapi-logs-list\backend\examples\ycc_logs_auth.py to YCCInnovationPython\backend\app\app\api\logs_auth.py. It checks YCC login tokens with the existing deps.get_user_token, so only signed-in users can read the logs.
4. In backend\app\app\main.py, add these lines right after app = FastAPI(...):
   from fastapi import Depends
   from app.logs_viewer import LogsSettings, install_log_capture
   from app.api.logs_auth import require_logs_access
   
   install_log_capture(
       app,
       settings=LogsSettings(api_prefix=f"{settings.API_V1_STR}/logs"),
       api_dependencies=[Depends(require_logs_access)],
   )
5. Add the MongoDB settings to the .env file in backend\app\app (the folder start.bat runs from). YCC ignores these lines, so sharing the file is safe:
   LOGS_MONGODB_URL=<your MongoDB URL>
   LOGS_MONGODB_DB=ycc_logs
   LOGS_SERVICE_NAME=ycc-api
   LOGS_ENVIRONMENT=production
   LOGS_RETENTION_DAYS=14
   LOGS_CAPTURE_PRINT=true
6. Restart YCC with start.bat, call any YCC endpoint, then open http://localhost:8005<API_V1_STR>/logs?range=1h&token=<a valid YCC token>. JSON with an items list means the backend part works.
Frontend: YCCInnovationWeb
1. Copy the folder fastapi-logs-list\frontend\src\app\logs to YCCInnovationWeb\src\app\logs.
2. In src\app\app.routes.ts, add a route next to the other admin pages:
   {
     path: 'logs',
     canActivate: [authGuard],
     loadChildren: () => import('./logs/logs.routes').then((m) => m.LOGS_ROUTES),
   },
3. In src\app\app.config.ts, add two providers. Use the same server address the rest of YCC calls, followed by logs:
   import { inject } from '@angular/core';
   import { LOGS_API_BASE, LOGS_EXTRA_PARAMS } from './logs/logs-api.service';
   import { AuthService } from './service/api/authToken.service';
   
   // inside providers: [ ... ]
   { provide: LOGS_API_BASE, useValue: 'https://<your YCC API address>/logs' },
   {
     provide: LOGS_EXTRA_PARAMS,
     useFactory: () => {
       const auth = inject(AuthService);
       return () => ({ token: auth.getToken() ?? '' });
     },
   },
4. Run npm start, sign in to YCC, and open /logs.
Optional polish: to show the page below a YCC header, give it the remaining height with app-logs-page { --logs-page-height: calc(100vh - 64px); } in a parent stylesheet. To change the title in the top bar, edit data: { title: ... } in logs\logs.routes.ts.
The full reference version of these steps, with notes on Gunicorn and HTTPS, is in docs\YCC_INTEGRATION.md in the project folder.
5. If something goes wrong
What you see
Likely cause and fix
activate fails in PowerShell with "running scripts is disabled"
Run Set-ExecutionPolicy -Scope CurrentUser RemoteSigned once, or use Command Prompt
"Could not reach logs MongoDB at startup" in the backend console
Wrong LOGS_MONGODB_URL, MongoDB not running, or your IP is not allowed on the hosted cluster
UI shows "Cannot reach the logs API"
Backend is not running on port 8000, or (in YCC) LOGS_API_BASE points to the wrong address
UI shows "Failed to load logs (HTTP 401)"
YCC token missing or expired; sign in again
UI loads but the table is empty
Timeline is set too short; switch to "Last 24 hours" or run the seed command
Requests appear but the Messages column is empty
That endpoint printed and logged nothing while it ran
npm start says the Node version is unsupported
Install Node 20 LTS and run npm install again