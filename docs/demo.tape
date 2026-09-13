# Reproducible demo. Render with: vhs docs/demo.tape  (https://github.com/charmbracelet/vhs)
Output docs/demo.gif
Set FontFamily "IBM Plex Mono"
Set FontSize 16
Set Width 900
Set Height 420
Set Theme "Catppuccin Latte"
Set TypingSpeed 40ms

Type "logbook init ~/Demo/Logbook" Enter
Sleep 1.5s
Type 'export LOGBOOK_HOME=~/Demo/Logbook' Enter
Sleep 800ms
Type 'logbook add "coffee with a friend by the lake"' Enter
Sleep 1.5s
Type "logbook show today" Enter
Sleep 2s
Type "logbook verify" Enter
Sleep 3s
