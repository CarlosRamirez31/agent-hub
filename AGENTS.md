# Codex Hub maintenance

- This is an independent project. Do not put its implementation into the dotfiles repository.
- Keep runtime dependencies in the Python standard library. Do not add telemetry, analytics, webviews, background update checks, remote scripts, or third-party service connections.
- The only hub maintenance network operation is an explicit Git update from `https://github.com/CarlosRamirez31/codex-hub.git`. Cloning from this same repository is the documented installation path.
- Launch the user's installed Codex CLI with argv arrays and no shell. Preserve its approvals, sandbox, and user configuration. Do not claim that the hub blocks Codex's own network traffic.
- Never read credentials or transcripts. Read Codex's SQLite metadata index only in read-only mode; do not write its databases or session files.
- Store organization separately under XDG_STATE_HOME. Demo mode must use memory and fictitious data.
- Import existing Codex projects and roots in read-only mode. Preserve empty locally added folders, nested project membership, and chronological recents.
- The sidebar contains folders and chat counts, without duplicate chat children. Moving its selection never changes the right pane; l/Enter/Tab explicitly enters the folder, and h returns to the sidebar. Enter on a chat resumes it; f explicitly forks. Never force another app's conversation lock.
- Keep Vim navigation, UTF-8 terminal text, small-terminal handling, and return-to-selector behavior working.
- Do not copy unlicensed code from the projects that inspired the idea.
- Run `python3 -B -m unittest discover -s tests -v` and `sh -n install.sh` before publishing changes.
