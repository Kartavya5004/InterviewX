# InterviewX 3.0 — Voice AI Interview Studio + Career OS

One local-first full-stack project combining your original **InterviewX Voice Studio**, account authentication, a Kanban job application tracker, course-based skill prescriptions, opt-in Gmail import, and Google Calendar export.

**Tech:** Python 3.10+ · FastAPI · SQLite · HTML/CSS/JavaScript · Gemini REST integration (optional) · Gmail REST API + OAuth 2.0 (optional) · Calendar REST API (optional).

## Included now

| Feature | How it works |
|---|---|
| Protected registration / login / logout | Argon2id password hashes, HttpOnly session cookie, CSRF checks, database-scoped user records |
| Voice-first AI practice | Keeps the working InterviewX 2.0 voice room, browser speech-recognition/TTS, adaptive follow-ups and Performance DNA reports |
| Company/application tracker | **Drag-and-drop Kanban** with Saved → Applied → Screening → Interview → Completed → Offer / Rejected; keyboard-friendly stage selector, manual forms, notes, actual recruiter feedback, interview dates |
| Learning prescriptions | Maps low practice scores / skills to a **curated, real course catalog** (PW Skills, CS50, Kaggle, freeCodeCamp, OpenLearn, etc.) and persists course progress per user |
| Learning missions | 3 tailored short exercises after practice, focused on DSA, AI/ML, communication or other areas |
| Gmail email intelligence | Google OAuth `gmail.readonly`, up to 30 messages per scan from the last 120 days with relevant keywords, explainable status/date suggestions, deduplication and **approval before importing** |
| Optional automatic Gmail checks | If enabled by the user, scans about every 15 minutes **while the local FastAPI server is running**. No scanning while the server is off |
| Interview planner | Generates preparation checklists when confirmed interview dates are saved in the tracker, either manually or via approved Gmail suggestions |
| Google Calendar | Separate OAuth `calendar.events` connection; click **Add to Google Calendar** per interview to insert a 60-minute event with reminders |
| Feedback intelligence | Aggregates patterns from **actual user-entered** recruiter feedback with supporting excerpts; doesn't invent reasons for rejection |

## Start immediately on Windows

1. **Extract the ZIP completely** to a new folder, e.g. `C:\Projects\InterviewX-3.0-Career-OS`. Don't mix with the older InterviewX directories.
2. Open the extracted folder and **double-click `start_windows.bat`**. The first launch creates `.venv` and installs dependencies. Keep the console open.
3. Open **http://127.0.0.1:8001/login** in Chrome / Edge. Don't use `8000` (that's often the old version).
4. Register your account, then select **Career cockpit** on the Voice Studio navigation bar or open **http://127.0.0.1:8001/career**.
5. Click **+ Track an application**. Add a role and date; try dragging its card to a new stage. Open **Interview planner** for your automatically generated preparation checklist.
6. Open **Inbox intelligence → Load fictional examples** to demonstrate an interview email without connecting any real Gmail account. Click **Review**, confirm data, then import into the tracker.
7. Open **Skill prescriptions** to review recommendations. Finish a voice interview for a more personalized skill focus.

### Run with VS Code PowerShell instead

Run commands **from inside the extracted project folder** (where `requirements.txt` is visible):

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m ensurepip --upgrade
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8001
```

**If `requirements.txt` is not found:** run `Get-Location` and `dir`, then `cd` to the directory where that file exists. If `pip._internal.utils` fails, delete only the project-local `.venv` folder and recreate it.

### Keep your account data from v2.1

If you have an **existing `interviewx.sqlite3` created by InterviewX 2.1 on your computer**, close both versions, make a backup, then copy the database into the **new** project's root *before* running InterviewX 3.0. The application automatically creates the new career tables. Don't copy `.venv` or mix the project source files. If you want a separate fresh account, simply don't copy the database.

## Turn on the Gemini interviewer (optional)

Copy `.env.example` to `.env` (the Windows launcher does this) and edit:

```env
GEMINI_API_KEY=replace_with_private_key
GEMINI_MODEL=gemini-2.5-flash
```

Restart FastAPI after changes. In demo mode you still get structural, transcript-based feedback, but **technical correctness is not reliably verified**. Browser microphone recognition relies on browser support/permissions and may be inaccurate; the transcript is editable before submission. The app does not directly upload raw microphone audio, though your browser may use an online speech-recognition service.

## How to connect Gmail + Google Calendar for real

**These steps are essential. The project does not include somebody else's Google credentials, and it cannot access your inbox without your approval.**

1. Go to [Google Cloud Console](https://console.cloud.google.com/) and create a project.
2. Enable **Gmail API** and **Google Calendar API** under APIs & Services → Library.
3. Configure the Google Auth Platform consent screen. Use **External / Testing** for the private hackathon demo (where applicable), add your own Google account as a **test user**, and declare the `gmail.readonly` and `calendar.events` scopes you will use.
4. Under Credentials, create an **OAuth 2.0 Client ID → Web application**.
5. Add this **exact authorized redirect URI**:

   `http://127.0.0.1:8001/api/google/callback`

   If you use `localhost` instead of `127.0.0.1`, update **both** the registered redirect and `.env` to match exactly.
6. Open `.env` and set:

```env
GOOGLE_CLIENT_ID=your_google_client_id
GOOGLE_CLIENT_SECRET=your_google_client_secret
GOOGLE_REDIRECT_URI=http://127.0.0.1:8001/api/google/callback
INTERVIEWX_TIMEZONE=Asia/Kolkata
```

7. Create a local encryption key using **the installed project's Python**:

```powershell
.\.venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

8. Paste the output into `.env`:

```env
INTERVIEWX_TOKEN_ENCRYPTION_KEY=paste_generated_key_here
```

9. Restart InterviewX. Sign in, open **Career cockpit → Inbox intelligence → Connect Gmail**. Review the Google consent screen and authorize the read-only scope. Connect Calendar separately if you also want Google Calendar export.
10. Click **Scan connected Gmail** to load suggestions. Only **Review → Confirm & Import** changes your career pipeline.
11. Turn on the separate **automatic checks** switch if you want periodic scans while InterviewX is running.
12. Create or approve an interview with a known date and time. Open **Interview planner → Add to Google Calendar** to create an event (only on your explicit action).

### What Gmail intelligence does *not* do

- It **doesn't know** what the true application status is just by reading an ambiguous email. Detection is heuristic. It may misunderstand the sender, company, role, or date. You must review/confirm the result.
- It **does not** sync Gmail continuously after your laptop shuts down; background checks are **local process only**, not a cloud service.
- It **does not** silently change statuses, create calendar events, delete emails, reply, or request your Gmail password.
- Dates are extracted only when email text contains explicit complete dates and times. Dates without a time remain blank for your review. Confirm timezone and meeting details yourself.
- Only a limited number of messages is scanned on demand or through the opt-in local polling loop. This is not full Gmail history or push notifications.
- Disconnecting Gmail removes the locally stored OAuth refresh credential and suggestion excerpts. Confirmed application records remain in your private career tracker. You can also revoke Google access in your Google Account.

**Google verification warning:** `gmail.readonly` is a **restricted OAuth scope**. Public production distribution may require Google verification and, depending on processing/storage and policies, a security assessment. A private hackathon demo with listed test users is different from an approved public production integration. Do not present public Gmail access as certified or production-ready.

## The course recommendation / partnership model

- The curated catalog links to actual education providers. It starts with free or open resources wherever possible, and PW Skills courses are included as optional choices.
- Courses are ranked by **training relevance**, based on practice categories, not by any compensation. The example app has **no existing sponsored partners**, affiliate agreements, tracking or commissions.
- If you partner with a course provider in the future, create a separately labeled **Sponsored** section with visible affiliate/sponsorship disclosure. Do not disguise promotions as objective personal recommendations.
- Provider prices, availability, syllabus and policies change; check the linked official page before presenting a price.

## Technical structure

```text
InterviewX-3.0-Career-OS/
├── backend/
│   ├── auth.py                # Passwords, sessions, CSRF, owner checks
│   ├── main.py                # Voice interview engine + FastAPI app
│   ├── career.py              # Kanban records, agenda, courses, progress, insights
│   └── google_integration.py  # OAuth, Gmail extraction/review, opt-in sync, Calendar
├── static/
│   ├── login.html / login.js / auth.css
│   ├── index.html / app.js / style.css      # Voice studio and charts
│   └── career.html / career.js / career.css # New career cockpit
├── tests/
│   ├── test_api.py            # Auth + interview tests
│   └── test_career.py         # New integration and owner-isolation tests
├── .env.example
├── requirements.txt
├── start_windows.bat
└── README.md
```

### Tests

```powershell
.\.venv\Scripts\python.exe -m pip install pytest
.\.venv\Scripts\python.exe -m pytest -q
```

The test suite checks session isolation, app creation, stage transitions, agenda creation, course progress, Gmail review approval, date parsing and a **fully mocked** Google OAuth → Gmail → Calendar workflow. *Real Gmail and Gemini calls cannot be tested without your keys and consent.*

## Before any public launch

This is a functional **local hackathon prototype** — not an audited multi-user SaaS. Before public deployment add verified email ownership, account recovery, MFA options, robust OAuth lifecycle and audit logging, encryption/key management, durable managed storage, account deletion/data export, privacy policy, legal review for restricted Google data, rate limiting on more endpoints, production monitoring, a dedicated background job service, and accessibility testing. SQLite on ephemeral cloud hosting may be lost. Avoid claiming AI practice scores predict job offers or measure psychological confidence.

### Official docs

- [Google OAuth web-server flow](https://developers.google.com/identity/protocols/oauth2/web-server)
- [Gmail message list](https://developers.google.com/workspace/gmail/api/guides/list-messages)
- [Restricted Gmail scopes](https://developers.google.com/workspace/gmail/api/auth/scopes)
- [Google Calendar event insertion](https://developers.google.com/workspace/calendar/api/v3/reference/events/insert)
