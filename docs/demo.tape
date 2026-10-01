# Reproducible demo. Render with: vhs docs/demo.tape  (https://github.com/charmbracelet/vhs)
# Record it from a throwaway home so the GIF never shows a real folder or name; the record it
# shows is `logbook demo`'s, a person who does not exist:
#   HOME=$(mktemp -d) PATH=$PWD/.venv/bin:$PATH vhs docs/demo.tape
Output docs/demo.gif
Set FontFamily "IBM Plex Mono"
Set FontSize 15
Set Width 1040
Set Height 520
Set Theme "Catppuccin Latte"
Set TypingSpeed 40ms

Type "logbook demo --out ~/Demo/Logbook" Enter
Sleep 3s
Type 'export LOGBOOK_HOME=~/Demo/Logbook' Enter
Sleep 800ms
Type "logbook trips" Enter
Sleep 4s
Type "clear" Enter
Type "logbook day 2026-06-17" Enter
Sleep 4s
Type "clear" Enter
Type "logbook rollup countries" Enter
Sleep 3s
Type "logbook verify" Enter
Sleep 3s
