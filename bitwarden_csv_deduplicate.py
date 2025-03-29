#!/usr/bin/env python3
"""
Bitwarden CSV Export Deduplication Tool

This script processes Bitwarden CSV exports to remove duplicate entries
and clean up login information, preserving critical data like TOTP.
"""

import csv
import sys
import re
import os
import ipaddress
import argparse
from collections import defaultdict
from urllib.parse import urlparse
from typing import Dict, List, Tuple, Optional


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Bitwarden CSV Export Deduplication Tool"
    )
    parser.add_argument(
        "-i", "--input", required=True, help="Input Bitwarden CSV export file path"
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Output deduplicated CSV file path (default: input_deduplicated.csv)",
    )
    parser.add_argument(
        "-f",
        "--filter",
        default="",
        help="Comma-separated keywords to filter out entries (in name, URL, or username)",
    )
    parser.add_argument(
        "-a",
        "--analyze",
        action="store_true",
        help="Run in analysis mode without creating output file",
    )
    parser.add_argument(
        "-d",
        "--default-folder",
        default="Personal",
        help="Default folder to use when folder is empty",
    )
    return parser.parse_args()


def normalize_url(url: str) -> str:
    """Normalize URL by ensuring proper scheme and removing trailing slashes."""
    if not url:
        return ""

    # Add scheme if missing
    if not url.startswith(("http://", "https://")):
        if url.startswith("www."):
            url = "https://" + url
        else:
            url = "https://" + url

    # Remove trailing slash
    url = url.rstrip("/")

    return url


def extract_domain(url: str) -> Optional[str]:
    """Extract and normalize domain from URL."""
    if not url:
        return None

    # Handle IP addresses
    if is_ip_address(url):
        return url

    # Check if it looks like a domain without scheme
    if not url.startswith(("http://", "https://", "www.")):
        if is_domain_name(url):
            return url

    # Try to parse as URL
    try:
        normalized_url = normalize_url(url)
        parsed = urlparse(normalized_url)
        domain = parsed.netloc

        # Remove www. prefix if present
        if domain.startswith("www."):
            domain = domain[4:]

        return domain if domain else None
    except Exception as e:
        print(f"Warning: Could not parse URL '{url}': {e}")
        return None


def is_ip_address(text: str) -> bool:
    """Check if text is a valid IP address."""
    try:
        ipaddress.ip_address(text)
        return True
    except ValueError:
        return False


def is_domain_name(text: str) -> bool:
    """Check if text resembles a domain name."""
    domain_pattern = r"^([a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$"
    return bool(re.match(domain_pattern, text))


def fix_login_uri(entry: Dict[str, str], default_folder: str) -> Dict[str, str]:
    """Update login_uri if empty but name contains valid domain/IP."""
    # Clone the entry so we don't modify the original
    updated_entry = entry.copy()

    # Only process if login_uri is empty and name has content
    if not updated_entry.get("login_uri") and updated_entry.get("name"):
        name = updated_entry["name"].strip()

        # Check if name is an IP address
        if is_ip_address(name):
            updated_entry["login_uri"] = f"https://{name}"
        # Check if name is a domain name
        elif is_domain_name(name):
            updated_entry["login_uri"] = f"https://{name}"
        # Check if name already has a scheme
        elif name.startswith(("http://", "https://")):
            updated_entry["login_uri"] = name

    # Set default folder if empty
    if not updated_entry.get("folder"):
        updated_entry["folder"] = default_folder

    return updated_entry


def should_remove_entry(entry: Dict[str, str], filter_keywords: List[str]) -> bool:
    """Check if an entry contains any filter keywords in name, URL, or username."""
    for keyword in filter_keywords:
        if (
            keyword.lower() in entry.get("name", "").lower()
            or keyword.lower() in entry.get("login_uri", "").lower()
            or keyword.lower() in entry.get("login_username", "").lower()
        ):
            return True
    return False


def get_grouping_key(entry: Dict[str, str]) -> Tuple:
    """Create grouping key for entries considering domain from URL."""
    name = entry.get("name", "")
    username = entry.get("login_username", "")
    password = entry.get("login_password", "")

    # Extract domain from URI if present
    uri = entry.get("login_uri", "")
    uri_domain = extract_domain(uri)

    # If we couldn't extract domain, use whole URI
    if not uri_domain and uri:
        uri_domain = uri

    # Consider TOTP as part of the key so entries with different TOTP are not considered duplicates
    totp = bool(entry.get("login_totp", ""))

    # Include notes in the key as they may contain important information
    notes = entry.get("notes", "")

    return (name, uri_domain, username, password, totp, bool(notes))


def select_best_entry(entries: List[Dict[str, str]]) -> Optional[Dict[str, str]]:
    """Select the best entry from a group of duplicates."""
    if not entries:
        return None

    if len(entries) == 1:
        return entries[0]

    # First prioritize entries with TOTP
    entries_with_totp = [e for e in entries if e.get("login_totp")]

    # Then prioritize entries with non-empty notes
    entries_with_notes = [e for e in entries if e.get("notes")]

    # Then prioritize entries with URI
    entries_with_uri = [e for e in entries if e.get("login_uri")]

    # Priority a: Entries with both TOTP and notes
    if entries_with_totp and entries_with_notes:
        both = [e for e in entries_with_totp if e in entries_with_notes]
        if both:
            return both[0]

    # Priority b: Entries with TOTP
    if entries_with_totp:
        return entries_with_totp[0]

    # Priority c: Entries with non-empty URI
    if entries_with_uri:
        return entries_with_uri[0]

    # Priority d: Entries with notes
    if entries_with_notes:
        return entries_with_notes[0]

    # Priority e: Look for entries with longest notes
    if entries:
        # Sort by notes length (longest first)
        sorted_by_notes = sorted(
            entries, key=lambda e: len(e.get("notes", "")), reverse=True
        )
        if sorted_by_notes[0].get("notes"):
            return sorted_by_notes[0]

    # Priority f: If all else fails, return the first entry
    return entries[0]


def main():
    """Execute the main deduplication process."""
    args = parse_arguments()

    input_file = args.input

    # Generate default output file name if not provided
    if not args.output:
        filename, ext = os.path.splitext(input_file)
        output_file = f"{filename}_deduplicated{ext}"
    else:
        output_file = args.output

    filter_keywords = [k.strip() for k in args.filter.split(",")] if args.filter else []
    default_folder = args.default_folder
    analysis_mode = args.analyze

    print("=== BITWARDEN DEDUPLICATION TOOL ===")
    print(f"Input file: {input_file}")
    print(f"Output file: {output_file}")
    print(f"Analysis mode: {'Enabled' if analysis_mode else 'Disabled'}")
    print(f"Filter keywords: {', '.join(filter_keywords)}")
    print(f"Default folder: {default_folder}")
    print("=" * 40)

    # Validate input file exists
    if not os.path.isfile(input_file):
        print(f"Error: Input file not found: {input_file}")
        sys.exit(1)

    # Read all entries
    print("\nSTEP 1: Reading CSV data...")
    login_entries = []
    other_entries = []  # Store non-login entries
    empty_folder_count = 0
    empty_uri_count = 0

    try:
        with open(input_file, "r", newline="", encoding="utf-8") as csvfile:
            reader = csv.DictReader(csvfile)
            headers = reader.fieldnames

            # Verify required fields exist
            required_fields = [
                "name",
                "login_uri",
                "login_username",
                "login_password",
                "login_totp",
                "folder",
                "type",
            ]
            missing_fields = [
                field for field in required_fields if field not in headers
            ]
            if missing_fields:
                print(
                    f"Error: Input CSV is missing required fields: {', '.join(missing_fields)}"
                )
                sys.exit(1)

            # Read entries, process login types and preserve others
            for row in reader:
                if row["type"] == "login":
                    if not row.get("folder"):
                        empty_folder_count += 1
                    if not row.get("login_uri"):
                        empty_uri_count += 1
                    login_entries.append(row)
                else:
                    # Store non-login entries to include in output
                    other_entries.append(row)
    except Exception as e:
        print(f"Error reading input file: {e}")
        sys.exit(1)

    print(f"Successfully read {len(login_entries)} login entries and {len(other_entries)} other entries from {input_file}")
    print(f"  - Login entries with empty folder: {empty_folder_count}")
    print(f"  - Login entries with empty login_uri: {empty_uri_count}")
    print(f"CSV column headers: {', '.join(headers)}")

    # Fix login_uri fields and empty folders
    print("\nSTEP 2: Fixing empty login_uri fields and setting default folders...")
    updated_entries = []
    uri_updates = 0
    folder_updates = 0

    for entry in login_entries:
        updated_entry = fix_login_uri(entry, default_folder)

        if updated_entry.get("login_uri") != entry.get("login_uri"):
            uri_updates += 1

        if updated_entry.get("folder") != entry.get("folder"):
            folder_updates += 1

        updated_entries.append(updated_entry)

    print(f"Fixed {uri_updates} empty login_uri fields")
    print(f"Set default folder for {folder_updates} entries with empty folders")

    # Filter entries with specific keywords
    print("\nSTEP 3: Filtering entries with specified keywords...")
    filtered_entries = []
    removed_by_filter = []

    for entry in updated_entries:
        if should_remove_entry(entry, filter_keywords):
            removed_by_filter.append(entry)
        else:
            filtered_entries.append(entry)

    print(f"Removed {len(removed_by_filter)} entries containing filter keywords")
    if removed_by_filter:
        print("All removed entries:")
        for i, entry in enumerate(removed_by_filter, 1):
            print(
                f"  {i}. {entry['name']} | URL: {entry.get('login_uri', '(empty)')} | "
                f"Username: {entry.get('login_username', '(empty)')}"
            )

    # Group entries for deduplication
    print("\nSTEP 4: Grouping entries for deduplication...")
    grouped = defaultdict(list)
    for entry in filtered_entries:
        key = get_grouping_key(entry)
        grouped[key].append(entry)

    unique_groups = {k: v for k, v in grouped.items() if len(v) == 1}
    duplicate_groups = {k: v for k, v in grouped.items() if len(v) > 1}

    print(f"Created {len(grouped)} unique groups")
    print(f"  - {len(unique_groups)} groups have a single entry (no duplicates)")
    print(f"  - {len(duplicate_groups)} groups have multiple entries (duplicates)")

    # Analyze duplicate groups
    print("\nSTEP 5: Analyzing duplicate entries...")

    entries_to_remove = 0
    entries_with_totp_kept = 0
    entries_with_notes_kept = 0
    entries_with_uri_kept = 0
    entries_basic_kept = 0

    if duplicate_groups:
        print("\nDetailed analysis of duplicate groups:")

        for idx, (key, group) in enumerate(duplicate_groups.items(), 1):
            name, uri_domain, username, _, has_totp, has_notes = key

            best_entry = select_best_entry(group)
            entries_to_remove += len(group) - 1

            # Count which type of entry was kept
            if best_entry.get("login_totp"):
                entries_with_totp_kept += 1
            elif best_entry.get("notes"):
                entries_with_notes_kept += 1
            elif best_entry.get("login_uri"):
                entries_with_uri_kept += 1
            else:
                entries_basic_kept += 1

            if analysis_mode or idx <= 10:  # Show first 10 groups in non-analysis mode
                print(
                    f"\n[Group {idx}] Name: {name} | Domain: {uri_domain or '(empty)'} | "
                    f"Username: {username or '(empty)'}"
                )
                print(f"  Total entries: {len(group)}")
                print(
                    f"  Group characteristics: {'Has TOTP' if has_totp else 'No TOTP'}, "
                    f"{'Has notes' if has_notes else 'No notes'}"
                )

                entries_with_uri = [e for e in group if e.get("login_uri")]
                entries_with_totp = [e for e in group if e.get("login_totp")]
                entries_with_notes = [e for e in group if e.get("notes")]

                print(f"  Entries with login_uri: {len(entries_with_uri)}/{len(group)}")
                print(f"  Entries with TOTP: {len(entries_with_totp)}/{len(group)}")
                print(f"  Entries with notes: {len(entries_with_notes)}/{len(group)}")

                kept_totp = "Yes" if best_entry.get("login_totp") else "No"
                kept_uri = "Yes" if best_entry.get("login_uri") else "No"
                kept_notes = "Yes" if best_entry.get("notes") else "No"

                print(
                    f"  DECISION: Keeping entry with TOTP: {kept_totp}, URI: {kept_uri}, "
                    f"Notes: {kept_notes}"
                )

                if analysis_mode:
                    print("  Entries in this group:")
                    for i, entry in enumerate(group, 1):
                        totp_status = (
                            "Has TOTP" if entry.get("login_totp") else "No TOTP"
                        )
                        uri_status = "Has URI" if entry.get("login_uri") else "No URI"
                        notes_status = "Has notes" if entry.get("notes") else "No notes"
                        action = "KEEP" if entry == best_entry else "REMOVE"
                        print(
                            f"    [{action}] Entry {i}: {entry['name']} | {totp_status} | "
                            f"{uri_status} | {notes_status} | Folder: {entry.get('folder', '(empty)')}"
                        )

        if len(duplicate_groups) > 10 and not analysis_mode:
            print(
                f"  ... and {len(duplicate_groups) - 10} more duplicate groups "
                f"(use --analyze for full details)"
            )

    # Select entries to keep
    print("\nSTEP 6: Selecting final entries...")
    final_entries = []

    # Add all unique entries
    for group in unique_groups.values():
        final_entries.append(group[0])

    # Add best entry from each duplicate group
    for group in duplicate_groups.values():
        final_entries.append(select_best_entry(group))

    # Summary statistics
    print("\nSummary of deduplication decisions:")
    print(f"  - Fixed {uri_updates} empty login_uri fields")
    print(f"  - Set default folder for {folder_updates} entries with empty folders")
    print(f"  - Removed {len(removed_by_filter)} entries by keyword filtering")
    print(f"  - Keeping {len(unique_groups)} unique entries (no duplicates)")
    print(
        f"  - Keeping {entries_with_totp_kept} entries with TOTP from duplicate groups"
    )
    print(
        f"  - Keeping {entries_with_notes_kept} entries with notes (but no TOTP) "
        f"from duplicate groups"
    )
    print(
        f"  - Keeping {entries_with_uri_kept} entries with URI (but no TOTP/notes) "
        f"from duplicate groups"
    )
    print(
        f"  - Keeping {entries_basic_kept} basic entries (no TOTP/notes/URI) "
        f"from duplicate groups"
    )
    print(f"  - Preserving {len(other_entries)} non-login entries (notes, cards, etc.)")
    print(f"  - Removing {entries_to_remove} duplicate entries")
    print(f"  - Final login entry count: {len(final_entries)}")
    print(f"  - Total removed login entries: {len(login_entries) - len(final_entries)}")
    print(f"  - Total entries in final output: {len(final_entries) + len(other_entries)}")

    # Write output file if not in analysis mode
    if not analysis_mode:
        print("\nSTEP 7: Writing deduplicated data to output file...")

        # Check if output file already exists
        if os.path.exists(output_file):
            print(f"Output file already exists, overwriting: {output_file}")

        try:
            with open(output_file, "w", newline="", encoding="utf-8") as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=headers)
                writer.writeheader()
                # Write deduplicated login entries
                writer.writerows(final_entries)
                # Also write other non-login entries
                writer.writerows(other_entries)
            print(f"Successfully wrote {len(final_entries)} login entries and {len(other_entries)} other entries to {output_file}")
        except Exception as e:
            print(f"Error writing output file: {e}")
            sys.exit(1)
    else:
        print("\nAnalysis mode: No output file was created.")

    print("\n=== DEDUPLICATION PROCESS COMPLETE ===")


if __name__ == "__main__":
    main()
