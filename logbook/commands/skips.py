"""The phrases for what an adapter counted: the skips (`skipped_*`) and the notes (a line written
with something worth knowing), as `add`, `sync` and `import-backup` print them after the count."""

from __future__ import annotations

LOCATION_SKIPS = ("skipped_no_timestamp", "skipped_bad_coordinates")


SKIP_PHRASES = {
    "skipped_no_timestamp": "without a timestamp",
    "skipped_bad_coordinates": "with unusable coordinates",
    "skipped_no_ref": "without a phone or email",
    "skipped_no_place": "without a departure place",
    "skipped_unknown_timezone": "with a timezone the zone database does not know",
    "skipped_empty_ref": "with an empty phone or email",
    "skipped_duplicate_ref": "with a phone or email already seen",
    "skipped_already_resolved": "already resolved in the record",
    "skipped_no_lid": "without a linked-device id",
    "skipped_no_phone": "without a usable phone number",
    "skipped_audiobook": "of an audiobook (RFC 0019 has tracks and episodes)",
    "skipped_not_a_play": "not a play (a start, a lyric view)",
    "skipped_duplicate_lid": "with a linked-device id already seen",
    "skipped_status": "in a status chat",
    "skipped_bad_date": "with an unusable date",
    "skipped_no_chat": "without a chat",
    "skipped_system_event": "group system events",
    "skipped_reaction": "reactions",
    "skipped_no_body": "without a body",
    "skipped_password_protected": "password protected",
    "skipped_no_text": "without any text",
    "skipped_no_title": "without a title",
    "skipped_no_url": "without a url",
    "skipped_ad": "advertisements",
    "skipped_never_played": "never played",
    "skipped_other_activity": "of another activity",
    "skipped_not_involved": "the owner is not part of",
    "skipped_no_owner": "with nobody to be the owner",
    "skipped_no_amount": "without an amount",
    "skipped_no_currency": "without a currency",
    "skipped_gift_cards": "gift cards",
    "skipped_covered_by_chrome": "Chrome visits, which google-takeout-chrome reads from Chrome/History.json",
    "skipped_encrypted": "encrypted with no decrypted copy in the store",
    "skipped_redacted": "redacted, or redactions",
    "skipped_call": "calls, not messages",
    "skipped_no_start": "without a start",
    "skipped_no_date": "without a date",
    "skipped_placeholder_date": "with a placeholder start (before 1900)",
    "skipped_bad_start": "with an unusable start",
    "skipped_no_uid": "without a uid",
    "skipped_todo": "to-do items",
    "skipped_journal": "journal entries",
    "skipped_empty": "with nothing in them",
    "skipped_no_bundle": "without a bundle id",
    "skipped_duplicate": "already seen",
    "skipped_web_domain": "per-site web time (the domain is never kept)",
    "skipped_sidecar_without_file": "sidecars without a media file",
    "skipped_unreadable_json": "JSON files that would not parse",
    "skipped_unreadable": "passes that would not parse",
    "skipped_no_flight": "boarding passes without a readable flight",
    "skipped_store_cards": "store and loyalty cards",
    "skipped_coupons": "coupons",
    "skipped_generic_passes": "generic passes",
    "skipped_unknown_style": "passes of no known style",
    "skipped_not_media": "files that are not media",
    "skipped_not_transcript": "files that are not transcripts",
    "skipped_unknown_subject": "of a vessel or aircraft not in assets.json",
    "skipped_not_a_position": "that are not position reports",
    "skipped_no_designator": "without a carrier and flight number",
    "skipped_no_route": "without both airports",
    "skipped_label": "by label",
    "skipped_no_value": "without a value",
    "skipped_bad_span": "ending before they start",
    "skipped_other_type": "of a type this version does not know",
    "skipped_unknown_stage": "with a sleep stage this version does not know",
    "skipped_over_cap": "over the one-per-minute heart-rate cap",
    "skipped_reading_position": "reading positions",
    "skipped_deleted": "deleted",
    "skipped_trashed": "in the trash",
    "skipped_relayed": "relayed from another app",
    "skipped_daily_total": "daily totals",
    "skipped_no_data": "days the provider had no values for (asked again next run)",
    "skipped_unreadable_csv": "CSV files without the columns this reader needs",
    "skipped_unreadable_row": "rows that would not parse",
}


NOTE_PHRASES = {  # counts that are not skips: the line was written, with something worth knowing
    "merged_into_known_people": "contacts merged into people the record knows",
    "no_chat_message_id": "without a message id, keyed by time and text",
    "no_owner": "with nobody named as the owner (owner_emails in logbook.json), so nothing is mine",
    "no_conference_id": "without a conference id, keyed by start and organizer",
    "no_transaction_id": "without a transaction id, keyed by time, merchant and amount",
    "media_stored": "with media stored",
    "no_stanza_id": "without a stanza id, keyed by row id",
    "no_guid": "without a guid, keyed by row id",
    "no_unique_id": "without a unique id, keyed by row id",
    "no_counterparty": "without a counterparty",
    "media_hashed": "with media hashed",
    "media_missing": "with media missing",
    "no_name": "without an app name",
    "deleted": "marked for deletion",
    "load_failed": "that did not load",
    "no_url": "of a removed video, without a url",
    "body_from_snippet": "with the body taken from the snippet",
    "no_identifier": "without an identifier, keyed by row id",
    "no_unique_identifier": "without a unique identifier, keyed by row id",
    "live_photo_pairs": "live-photo pairs",
    "no_sidecar": "without a sidecar",
    "at_from_creation_time": "timed by creation time",
    "at_from_file_time": "timed by the file",
    "direct_chat": "in direct chats",
    "group_chat": "in group chats",
    "no_summary": "without a summary",
    "no_recording": "without a recording (summary only)",
    "merged": "merged into a flight already in the record",
    "corrected": "corrected: a later export changed a sample, the line in the record is superseded",
    "no_airport_zone": "with an airport the table does not know",
    "arrival_before_departure": "arriving before departing, kept as given",
    "no_gap": "calendar flights the location points do not confirm",
    "covered": "legs a tracked flight already covers",
    "no_message_id": "without a Message-ID, keyed by digest",
    "date_from_separator": "timed by the mbox separator (no Date header)",
    "body_from_html": "with the body taken from HTML",
    "decoding_errors": "with undecodable bytes replaced",
    "attachments_referenced": "attachments referenced, not stored",
    "attachments_stored": "attachments stored",
    "attachments_missing": "attachments missing from the export",
    "trashed": "marked trashed",
    "pending": "still pending",
    "from_last_message": "from a room's last-message row (not in the event cache)",
    "owner_guessed": "owner taken as the person on most expenses (no owner_emails matched)",
    "no_title": "without a title",
}


def _report_skipped(counts: dict[str, int]) -> None:
    """One line naming what an adapter left out and why, or nothing when it skipped nothing."""
    no_time = counts.get("skipped_no_timestamp", 0)
    bad_coords = counts.get("skipped_bad_coordinates", 0)
    if no_time or bad_coords:
        print(f"  skipped {no_time:,} without a timestamp, {bad_coords:,} with unusable coordinates")
    others = [
        f"{n:,} {SKIP_PHRASES.get(key, key.removeprefix('skipped_').replace('_', ' '))}"
        for key, n in counts.items()
        if key not in LOCATION_SKIPS and key.startswith("skipped_") and n
    ]
    if others:
        print("  skipped " + ", ".join(others))
    noted = [
        f"{n:,} {NOTE_PHRASES.get(key, key.replace('_', ' '))}"
        for key, n in counts.items()
        if not key.startswith("skipped_") and n
    ]
    if noted:
        print("  also " + ", ".join(noted))
