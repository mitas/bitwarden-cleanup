# Bitwarden Management Tools

This repository contains tools for managing Bitwarden password manager vault data, including deduplication and bulk operations.

## Tools Overview

1. **bitwarden_csv_deduplicate.py** - A Python script to deduplicate and clean Bitwarden CSV exports
2. **bitwarden_bulk_delete.go** - A Go script for bulk deletion of Bitwarden items with parallel processing

## Bitwarden CSV Deduplicator

The `bitwarden_csv_deduplicate.py` script processes Bitwarden CSV exports to remove duplicates and filter unwanted entries.

### Features

- Deduplicates login-type entries based on name, domain, username, and password
- Preserves non-login entries (notes, cards, identities) in the output unchanged
- Filters entries containing specified keywords
- Fixes empty login URI fields by extracting domains from names
- Sets a default folder for entries with empty folders
- Preserves entries with TOTP and detailed notes

### Usage

Basic usage:

```bash
python bitwarden_csv_deduplicate.py -i bitwarden_export.csv
```

Advanced usage with all options:

```bash
python bitwarden_csv_deduplicate.py -i bitwarden_export.csv -o custom_output.csv -f "keyword1,keyword2,keyword3" -d "My Folder" -a
```

### Command Line Arguments

| Option | Description |
|--------|-------------|
| `-i, --input` | Input Bitwarden CSV export file path (required) |
| `-o, --output` | Output deduplicated CSV file path (default: input_deduplicated.csv) |
| `-f, --filter` | Comma-separated keywords to filter out entries |
| `-a, --analyze` | Run in analysis mode without creating output file |
| `-d, --default-folder` | Default folder to use when folder is empty (default: "Personal") |

### Deduplication Rules

When multiple entries have the same name, domain, username, and password, the script selects which entry to keep using the following priority order:

1. Entries with both TOTP and notes (highest priority)
2. Entries with TOTP
3. Entries with non-empty URI
4. Entries with notes
5. Entries with the longest notes
6. First entry (last resort)

### Example

To deduplicate a Bitwarden export and filter out entries containing specific keywords:

```bash
python bitwarden_csv_deduplicate.py -i bitwarden_export.csv -f "example, beta, nexus, admin, test"
```

### Example Output

When running the script with filter keywords, you'll see output similar to this:

```
=== BITWARDEN DEDUPLICATION TOOL ===
Input file: bitwarden_export_20250329.csv
Output file: bitwarden_export_20250329_deduplicated.csv
Analysis mode: Disabled
Filter keywords: example, beta, nexus, admin, test
Default folder: Personal
========================================

STEP 1: Reading CSV data...
Successfully read 1205 login entries and 78 other entries from bitwarden_export_20250329.csv
  - Login entries with empty folder: 143
  - Login entries with empty login_uri: 512
CSV column headers: folder, favorite, type, name, notes, fields, reprompt, login_uri, login_username, login_password, login_totp

STEP 2: Fixing empty login_uri fields and setting default folders...
Fixed 435 empty login_uri fields
Set default folder for 143 entries with empty folders

STEP 3: Filtering entries with specified keywords...
Removed 87 entries containing filter keywords
All removed entries:
  1. example.com | URL: https://example.com | Username: test.user@example.com
  2. beta.example.com | URL: https://beta.example.com | Username: admin@example.com
  3. nexus.example.com | URL: https://nexus.example.com | Username: developer@example.com
  4. admin.example.com | URL: https://admin.beta.example.com | Username: admin@example.com
  5. test.example.com | URL: https://test.example.com | Username: tester@example.com
  ... [remaining entries omitted for brevity]

STEP 4: Grouping entries for deduplication...
Created 1093 unique groups
  - 1082 groups have a single entry (no duplicates)
  - 11 groups have multiple entries (duplicates)

STEP 5: Analyzing duplicate entries...

Detailed analysis of duplicate groups:

[Group 1] Name: mail.example.com | Domain: mail.example.com | Username: user1
  Total entries: 2
  Group characteristics: Has TOTP, Has notes
  Entries with login_uri: 2/2
  Entries with TOTP: 1/2
  Entries with notes: 2/2
  DECISION: Keeping entry with TOTP: Yes, URI: Yes, Notes: Yes

[Group 2] Name: cloud.example.org | Domain: cloud.example.org | Username: admin
  Total entries: 3
  Group characteristics: No TOTP, Has notes
  Entries with login_uri: 3/3
  Entries with TOTP: 0/3
  Entries with notes: 2/3
  DECISION: Keeping entry with TOTP: No, URI: Yes, Notes: Yes
  
  ... [remaining groups omitted for brevity]

STEP 6: Selecting final entries...

Summary of deduplication decisions:
  - Fixed 435 empty login_uri fields
  - Set default folder for 143 entries with empty folders
  - Removed 87 entries by keyword filtering
  - Keeping 1082 unique entries (no duplicates)
  - Keeping 4 entries with TOTP from duplicate groups
  - Keeping 3 entries with notes (but no TOTP) from duplicate groups
  - Keeping 2 entries with URI (but no TOTP/notes) from duplicate groups
  - Keeping 2 basic entries (no TOTP/notes/URI) from duplicate groups
  - Preserving 78 non-login entries (notes, cards, etc.)
  - Removing 14 duplicate entries
  - Final login entry count: 1093
  - Total removed login entries: 101
  - Total entries in final output: 1171

STEP 7: Writing deduplicated data to output file...
Successfully wrote 1093 login entries and 78 other entries to bitwarden_export_20250329_deduplicated.csv

=== DEDUPLICATION PROCESS COMPLETE ===
```

The script provides detailed information about:
- The number of entries processed
- Fixes applied to empty fields
- Entries filtered based on keywords
- Duplicate groups identified
- Decision logic for which entries to keep
- Final statistics on deduplicated data

## Bitwarden Bulk Delete Tool

The `bitwarden_bulk_delete.go` script helps delete multiple Bitwarden items in parallel.

### Features

- Processes deletions in parallel (1 item at a time by default)
- Supports searching for specific items
- Standard deletion (to trash) by default with option for permanent deletion
- Confirms deletion to prevent accidental data loss
- Syncs Bitwarden vault before starting and after completion
- Displays sync command output for better visibility
- Rich emoji-based output for better readability
- Checks if required Bitwarden CLI is installed
- Uses standard Go packages with no external dependencies

### Usage

First, compile the Go script:

```bash
go build -o bitwarden_bulk_delete bitwarden_bulk_delete.go
```

Basic usage:

```bash
./bitwarden_bulk_delete
```

Advanced usage with options:

```bash
./bitwarden_bulk_delete --search 'keyword' --batch 10
```

You can also use short flag names:

```bash
./bitwarden_bulk_delete -s 'keyword' -b 10
```

### Command Line Arguments

| Option | Short | Description |
|--------|-------|-------------|
| `--search` | `-s` | Search term to filter items (optional) |
| `--batch` | `-b` | Number of items to process in parallel (default: 1) |
| `--permanent` | `-p` | Permanently delete items (bypass trash) |

### Examples

To delete all items containing "test" in their name (moves to trash):

```bash
./bitwarden_bulk_delete --search 'test'
```

To permanently delete all items containing "temporary" with 10 parallel workers:

```bash
./bitwarden_bulk_delete --search 'temporary' --batch 10 --permanent
```

Using short flags for permanent deletion:

```bash
./bitwarden_bulk_delete -s 'temporary' -b 10 -p
```

### Example Output

Here's what the output looks like when running the command with 20 parallel workers:

```
ℹ️ Mode: Standard deletion (items will go to trash)
🔄 Syncing Bitwarden database before starting...
✅ Initial sync completed successfully
✅ Command output: Syncing complete.

🔍 Fetching Bitwarden items...
🔍 Found 933 items to delete

⚠️ Are you sure you want to delete all 933 items? (y/N) y
🚀 Starting deletion process...
⏳ Progress: [933/933]

🎉 All 933 items have been moved to trash!
🔄 Syncing Bitwarden database...
✅ Sync completed successfully
✅ Command output: Syncing complete.
```

When using the `--permanent` flag, the mode and final message will indicate permanent deletion instead:

```
⚠️ Mode: Permanent deletion (items will bypass trash)
🔄 Syncing Bitwarden database before starting...
...
🔍 Fetching Bitwarden items...
🔍 Found 933 items to delete
...
⚠️ Are you sure you want to PERMANENTLY delete all 933 items? (y/N) y
...
🎉 All 933 items have been permanently deleted!
...
```

## Prerequisites

### For bitwarden_csv_deduplicate.py
- Python 3.6+
- CSV export from Bitwarden

### For bitwarden_bulk_delete.go
- Go 1.13+
- Bitwarden CLI (`bw`) installed and in your PATH
- Logged in to Bitwarden CLI (`bw login`)

## Safety Notes

- **Always back up your Bitwarden vault before using these tools**
- Run in analysis mode first to review what will be deleted/changed
- Permanent deletions cannot be undone
- **DISCLAIMER:** The author is not responsible for any data loss that may occur when using these tools. Use at your own risk.
