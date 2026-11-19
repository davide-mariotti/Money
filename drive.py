"""Google Drive / Gmail through the official REST APIs, stdlib only, with the user's own OAuth client.
Setup once: an OAuth client "App desktop" saved as data/google_client.json; the first run opens the browser to allow,
then the refresh token stays in data/google_token.json (both in data/: never on git).
  .venv\\Scripts\\python drive.py                  upload to <settings.drive_folder>/<cartella>/ the PDFs not there yet,
                                                 then money-backup-<date>.zip (everything git doesn't have, see backup; last 3 kept)
  .venv\\Scripts\\python drive.py gmail "<query>"  save the PDF attachments (also inside .zip) of the matching mails in data/nuovi/
PDFs in data/<cartella>/ were already shrunk at import (money.shrink_pdf)."""
import base64, hashlib, io, json, re, secrets, sqlite3, subprocess, sys, tempfile, urllib.error, webbrowser, zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen
import money

CLIENT, TOKEN = money.DATA / "google_client.json", money.DATA / "google_token.json"
SCOPES = "https://www.googleapis.com/auth/drive https://www.googleapis.com/auth/gmail.readonly"
FILES, UPLOAD = "https://www.googleapis.com/drive/v3/files", "https://www.googleapis.com/upload/drive/v3/files"
GMAIL, FOLDER = "https://gmail.googleapis.com/gmail/v1/users/me/messages", "application/vnd.google-apps.folder"
_access = None


def token():
    global _access
    if _access:
        return _access
    c = json.loads(CLIENT.read_text())["installed"]
    post = lambda **f: json.loads(urlopen(c["token_uri"], urlencode(
        {"client_id": c["client_id"], "client_secret": c["client_secret"], **f}).encode()).read())
    if TOKEN.exists():
        try:
            _access = post(refresh_token=json.loads(TOKEN.read_text())["refresh_token"], grant_type="refresh_token")["access_token"]
            return _access
        except urllib.error.HTTPError:  # revoked, or expired (an app left "in test" loses it after 7 days): log in again
            pass
    got, state, verifier = {}, secrets.token_urlsafe(16), secrets.token_urlsafe(48)

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            got.update(parse_qs(urlparse(self.path).query))
            self.send_response(200)
            self.end_headers()
            self.wfile.write("Fatto: puoi chiudere questa scheda.".encode())

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    redirect = f"http://127.0.0.1:{srv.server_port}"
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    webbrowser.open(c["auth_uri"] + "?" + urlencode(dict(
        client_id=c["client_id"], redirect_uri=redirect, response_type="code", scope=SCOPES, access_type="offline",
        prompt="consent", state=state, code_challenge=challenge, code_challenge_method="S256")))
    while "code" not in got and "error" not in got:
        srv.handle_request()
    if got.get("state") != [state] or "error" in got:
        raise SystemExit(f"accesso non riuscito: {got.get('error', ['state diverso'])[0]}")
    t = post(code=got["code"][0], redirect_uri=redirect, grant_type="authorization_code", code_verifier=verifier)
    TOKEN.write_text(json.dumps({"refresh_token": t["refresh_token"]}))
    _access = t["access_token"]
    return _access


def api(url, data=None, ctype="application/json", method=None):
    with urlopen(Request(url, data, {"Authorization": "Bearer " + token(), "Content-Type": ctype}, method=method)) as r:
        return json.loads(r.read())


def children(parent, folders=False):
    q = f"'{parent}' in parents and trashed=false and mimeType {'=' if folders else '!='} '{FOLDER}'"
    # ponytail: one page of 1000 per folder, loop on nextPageToken if a folder ever gets that big
    return {f["name"]: f["id"] for f in api(FILES + "?" + urlencode({"q": q, "fields": "files(id,name)", "pageSize": 1000}))["files"]}


def upload():
    db = money.connect()
    root = money.setting(db, "drive_folder") or sys.exit("manca settings.drive_folder (id della cartella Drive)")
    todo = {}
    for p in sorted(money.DATA.glob("*/*.pdf")):
        if p.parent.name.lower() not in ("nuovi", "archivio"):
            todo.setdefault(p.parent.name.lower(), []).append(p)
    subs = children(root, folders=True)
    for sub, files in todo.items():
        if sub not in subs:
            subs[sub] = api(FILES, json.dumps({"name": sub, "parents": [root], "mimeType": FOLDER}).encode())["id"]
        there = children(subs[sub])
        new = [p for p in files if p.name not in there]
        for p in new:
            put(p.read_bytes(), "application/pdf", name=p.name, parent=subs[sub])
        print(sub, [p.name for p in new] or "tutto già su Drive")
    name, data, there = f"money-backup-{date.today()}.zip", backup(), children(root)
    put(data, "application/zip", fid=there[name]) if name in there else put(data, "application/zip", name=name, parent=root)
    old = sorted(n for n in there if re.fullmatch(r"money-backup-\d{4}-\d\d-\d\d\.zip", n) and n != name)
    for n in old[:max(0, len(old) - 2)]:  # keep the newest 3, today's included; the rest to the Drive bin (30 days)
        api(f"{FILES}/{there[n]}", json.dumps({"trashed": True}).encode(), method="PATCH")
    print(f"{name}: {len(data) / 1e6:.1f} MB", f"· nel cestino: {old[:max(0, len(old) - 2)]}" if len(old) > 2 else "")


def put(data, mime, name=None, parent=None, fid=None):
    """Resumable upload (the simple one stops at 5 MB): a new file in `parent`, or new content for the file `fid`."""
    start = Request(f"{UPLOAD}{'/' + fid if fid else ''}?uploadType=resumable",
                    json.dumps({"name": name, "parents": [parent]} if parent else {}).encode(),
                    {"Authorization": "Bearer " + token(), "Content-Type": "application/json; charset=UTF-8",
                     "X-Upload-Content-Type": mime}, method="PATCH" if fid else "POST")
    with urlopen(start) as r:
        session = r.headers["Location"]
    with urlopen(Request(session, data, {"Content-Type": mime}, method="PUT")) as r:
        return json.loads(r.read())


def backup():
    """Everything git doesn't track (data/ with the PDFs, local notes), one zip. New PC: git clone, then unzip it in the
    repo folder. OAuth token included (the user wants it: a new PC works at once while it is valid)."""
    repo, buf = money.DATA.parent, io.BytesIO()
    local = subprocess.run(["git", "ls-files", "-z", "--others"], cwd=repo, capture_output=True, encoding="utf-8",
                           check=True).stdout.split("\0")
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z, tempfile.TemporaryDirectory() as tmp:
        snap = Path(tmp) / "money.db"
        src, dst = sqlite3.connect(money.DB), sqlite3.connect(snap)
        src.backup(dst)  # consistent copy even while the app is writing
        src.close(), dst.close()  # Windows can't delete the temp dir with the file still open
        z.write(snap, "data/money.db")
        for n in sorted(local):
            if n and n != "data/money.db" and not n.startswith(".venv/") and "__pycache__/" not in n:
                z.write(repo / n, n, zipfile.ZIP_STORED if n.lower().endswith(".pdf") else None)
    return buf.getvalue()


def gmail(query):
    ids, page = [], ""
    while True:
        r = api(GMAIL + "?" + urlencode({"q": query, "maxResults": 500, "pageToken": page}))
        ids += [m["id"] for m in r.get("messages", [])]
        if not (page := r.get("nextPageToken")):
            break
    money.INBOX.mkdir(exist_ok=True)
    n = 0
    for mid in ids:
        stack = [api(f"{GMAIL}/{mid}")["payload"]]
        while stack:
            p = stack.pop()
            stack += p.get("parts", [])
            if p.get("filename", "").lower().endswith((".pdf", ".zip")) and "attachmentId" in p["body"]:
                data = base64.urlsafe_b64decode(api(f"{GMAIL}/{mid}/attachments/{p['body']['attachmentId']}")["data"])
                z = zipfile.ZipFile(io.BytesIO(data)) if p["filename"].lower().endswith(".zip") else None
                for name, read in [(i.filename, lambda i=i: z.read(i)) for i in z.infolist() if i.filename.lower().endswith(".pdf")] \
                        if z else [(p["filename"], lambda: data)]:
                    name = re.sub(r"[^\w.-]", "_", name.replace("\\", "/").split("/")[-1])  # names from mail/zip are untrusted
                    (money.INBOX / f"{mid}_{name}").write_bytes(read())
                    n += 1
    print(f"{len(ids)} mail, {n} PDF in {money.INBOX}")


if __name__ == "__main__":
    gmail(sys.argv[2]) if sys.argv[1:2] == ["gmail"] else upload()
