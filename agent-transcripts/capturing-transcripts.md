# Capturing and scrubbing the raw agent transcript

Cursor persists each agent session as JSONL on the local machine. This is the procedure to
export one and make it safe to share.

## 1. Locate the log

```
%USERPROFILE%\.cursor\projects\<project-slug>\agent-transcripts\<session-id>\<session-id>.jsonl
```

For this project the slug is `d-github-lenny-growth-assistant`. Each session is one
directory named by its id, containing a `.jsonl` file with one JSON event per line
(user messages, assistant messages, and metadata).

macOS/Linux equivalent:

```
~/.cursor/projects/<project-slug>/agent-transcripts/<session-id>/<session-id>.jsonl
```

## 2. Export

```powershell
# PowerShell
$src = "$env:USERPROFILE\.cursor\projects\d-github-lenny-growth-assistant\agent-transcripts"
Copy-Item -Recurse $src .\agent-transcripts\raw\
```

```bash
# bash
cp -r ~/.cursor/projects/d-github-lenny-growth-assistant/agent-transcripts ./agent-transcripts/raw/
```

## 3. Scrub before sharing

Check for and remove, in this order:

1. **Credentials.** Search for `sk-ant-`, `sk-`, `api_key`, `password`, `token`, `secret`,
   `Bearer `. In this project's session no key was ever entered — the Anthropic path was
   deliberately left unconfigured — but verify rather than assume.

   ```powershell
   Select-String -Path .\agent-transcripts\raw\**\*.jsonl `
     -Pattern 'sk-ant-|sk-[A-Za-z0-9]{20,}|Bearer |password|secret|token' |
     Select-Object Path, LineNumber
   ```

2. **Absolute local paths**, which leak the OS user name.

   ```powershell
   (Get-Content .\file.jsonl -Raw) `
     -replace 'D:\\github\\lenny-growth-assistant', '<REPO>' `
     -replace 'C:\\Users\\[^\\"]+', '<HOME>' |
     Set-Content .\file.scrubbed.jsonl
   ```

3. **Transcript content.** If real podcast transcripts were pasted or read during the
   session, that content is third-party material — remove it rather than redistributing it.

4. **Anything else personal** — unrelated file paths, other project names, machine
   identifiers.

## 4. Verify, then commit

```powershell
Select-String -Path .\*.scrubbed.jsonl -Pattern 'sk-|Bearer |C:\\Users\\|D:\\github'
```

An empty result means it is safe to attach. Commit only scrubbed files, and never commit
`.env` (it is git-ignored).

## Making the log readable

The JSONL is one event per line and some lines are very large. To skim the conversation
without the tool-call noise:

```bash
# roles and first 160 chars of each message
python -c "
import json,sys
for line in open(sys.argv[1], encoding='utf-8'):
    try: e = json.loads(line)
    except ValueError: continue
    role, text = e.get('role'), str(e.get('content') or '')
    if role: print(f'[{role}] {text[:160].replace(chr(10), \" \")}')
" session.jsonl
```
