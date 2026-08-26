## User/local context
- Address the user using their preferred name or title; keep responses concise and polished.
- The user is in <city, region>; show local times in <timezone>.
- Define any local aliases for Cast devices, speakers, lights, plugs, or other equipment here.
- Document required tool-loading and safety rules for home-control requests here.
- Document purifier or other device-specific control paths here.
- State the canonical local host/root and reserve SSH for explicit remote hosts. Keep connection details in ignored config files.
- Record the project-specific Pi session JSONL directory under `~/.pi/agent/sessions/`. For prior-session questions, use `rg -l` with distinctive literal terms, then parse/read only the small set of matching files; never bulk-load the session directory.
