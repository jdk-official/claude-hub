# Memory index

The facts index — loaded each session for recall. One line per memory: a short
pointer to a durable fact about the project. No content lives here; each line
points at where the detail lives (a note, an ADR, a section of context).

Keep it to pointers. When a fact stops being true, remove or update its line.

- claude-hub is launched with `ghostty -e claude-hub`; the user's Ghostty window is tiled and narrow (~384 px).
