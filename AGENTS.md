# Agent Hub maintenance

- This is an independent project. Do not put its implementation into the dotfiles repository.
- Keep runtime dependencies in the Python standard library. Do not add telemetry, analytics, webviews, background update checks, remote scripts, or third-party service connections.
- The only hub maintenance network operation is an explicit Git update from `https://github.com/CarlosRamirez31/agent-hub.git`. Cloning from this same repository is the documented installation path.
- Launch the user's installed Codex CLI with argv arrays and no shell. Preserve its approvals, sandbox, and user configuration. Do not claim that the hub blocks Codex's own network traffic.
- Never read credentials, hidden reasoning or tool results. Native indexes are read-only for browsing. The user explicitly authorized confirmed deletion of original conversations and entire project directories: use native deletion APIs/CLI, never direct native database writes; require a separate explicit typed confirmation for each deletion, and a reviewed cross-agent plan before recursive directory removal. The user authorized reading user/assistant conversation text for selected context transfers and explicit message synchronization. Store normalized data in the hub's private SQLite database; never directly modify native databases or session files. Native agents own deletion through their APIs/CLI.
- Store organization separately under XDG_STATE_HOME. Demo mode must use memory and fictitious data.
- Import existing Codex projects and roots in read-only mode. Preserve empty locally added folders, nested project membership, and chronological recents.
- The sidebar contains folders and chat counts, without duplicate chat children. Moving its selection never changes the right pane; l/Enter/Tab explicitly enters the folder, and h returns to the sidebar. Enter on a chat resumes it; f explicitly forks. Never force another app's conversation lock.
- Keep Vim navigation, UTF-8 terminal text, small-terminal handling, and return-to-selector behavior working.
- Do not copy unlicensed code from the projects that inspired the idea.
- Do not modify Coucou, its launchers or dotfiles. Its future integration is a documented JSON/CLI contract only.
- Run `python3 -B -m unittest discover -s tests -v` and `sh -n install.sh` before publishing changes.
