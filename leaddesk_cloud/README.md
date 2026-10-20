# LeadDesk Cloud — Telegram public-job response queue

Headless web version of LeadDesk for Railway. **This is not a mass DM tool.** It sends tailored responses only to recent, publicly posted requests for contractors. Every recipient needs an individually reviewed message and source link; manual approval and campaign start are required. Default state is paused.

## Railway setup
- Deploy this folder as a separate service (root directory `leaddesk_cloud`) attached to a persistent volume at `/data`.
- Set `ADMIN_PASSWORD` to a strong, unique secret of 16+ characters. User name: `admin`. The console refuses access until the password exists.
- Set `TG_API_ID`, `TG_API_HASH` (obtain via [my.telegram.org](https://my.telegram.org)), and `TG_STRING_SESSION` in Railway **Variables**, NEVER in GitHub.
- Generate session **locally** using `python export_session.py` with `pip install -r requirements.txt`; copy the output into Railway Variables. Only authorize your own Telegram account. Losing control of the string session may compromise the account.
- Use the generated HTTPS Railway domain. The `/health` endpoint is public and exposes only the text `ok`; all other pages require Basic Auth.
- Import JSON/CSV. Add recent direct public posting link, date, tailored message, and approve each contact. Then check the confirmation and start. You can close the PC; the persistent queue remains on the Railway volume.
- **No contacts are sent anything on deploy**. No automated contact discovery or bulk sending to arbitrary accounts.

## Limits and controls
- Hard caps: 5 successful messages / 24 hours, 3 / hour, ≥45 seconds between sends.
- Stops on `FloodWaitError`, `PeerFloodError` or missing authorization; never bypass Telegram restrictions.
- Mark `sending` before network call, and never automatically retry uncertain sends after crash. Manually check Telegram before reconciling.
- No rotating accounts, proxies, scraping private chats, or secrets in source code.
- Need a person to have **publicly requested offers**; otherwise don't use the sender.

CSV fields: `username,project,service,message,source_url,posted_on` (YYYY-MM-DD). For Telegram links use direct public posts `https://t.me/channel/12345`, not a profile link.

The SQLite database under `/data/leaddesk.sqlite3` is private. Back it up periodically. A volume is mandatory for durable state.

## Safety
A Railway deployment incurs hosting charges. Stop the service when no longer needed. Telegram may still restrict an account if people report your messages, even with conservative rates.