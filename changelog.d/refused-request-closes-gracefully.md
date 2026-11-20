### Fixed
- A request the Library refuses before reading its body (a proxy's POST, another host's, a form over
  the size it may carry) is now closed gracefully: after the answer, at most 64 KiB of the unread body
  are read and dropped, never parsed, for at most a second, so the client always reads the refusal.
  On Windows the client could see the connection reset (WinError 10053) before the answer arrived.
