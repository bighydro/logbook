### Adapters
- `logbook add instagram <zip|folder>` reads Instagram's "Export your information" archive (JSON, the
  older and the newer folder layout alike): direct messages from the inbox, message requests and archived
  chats as messages, calls as calls, the images and videos of your posts, stories and reels as photos with
  their caption and place, and follows, close friends, blocks, restrictions, follow requests, unfollows,
  likes, comments, story likes and profile searches as `social/v1` lines (RFC 0048, a draft). Meta's
  garbled text (`Ã¥` for `å`) is read back as written. Adding the same export again writes nothing; a newer
  one adds only what is new. An HTML export is refused with how to ask for JSON. Instagram senders are
  proposed against the people you know by name in `people review`, never merged on their own.
  See docs/adapters/instagram.md.
