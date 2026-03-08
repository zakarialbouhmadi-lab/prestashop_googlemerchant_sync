# prestashop-google-merchant-sync

A Python script that exports active product variants from a **PrestaShop** database directly into **Google Sheets**, in the format expected by **Google Merchant Center** (main product feed + local inventory feed).

It is designed to run on a schedule (e.g. via cron) and sends an email notification on success or failure.

---

## Features

- Queries the PrestaShop MySQL database directly — no API key needed
- Populates a **main product feed** spreadsheet (title, price, stock, images, attributes, etc.)
- Populates a **local inventory feed** spreadsheet (stock & price per store)
- Handles VAT, promotions (percentage & fixed), and unit pricing
- Parses Polish product descriptions to extract highlights, material, and technical details
- Batches Google Sheets writes for performance
- Sends Gmail notifications on completion or error
- Fully configurable via a single `parameters.txt` file

---

## Project Structure

```
.
├── sync.py                          # Main script
├── parameters.txt                   # Your local config (not committed — see .gitignore)
├── parameters.txt.example           # Config template with placeholders
├── spreadsheet-service-account-key.json   # Google service account key (not committed)
├── logs/                            # Auto-created; one log file per run date
└── requirements.txt
```

---

## Prerequisites

- Python 3.8+
- A PrestaShop MySQL database accessible from the machine running the script
- A Google Cloud project with the **Google Sheets API** enabled
- A **service account** with editor access to both spreadsheets ([guide](https://developers.google.com/workspace/guides/create-credentials#service-account))
- A **Gmail App Password** for email notifications ([guide](https://support.google.com/accounts/answer/185833))

---

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/your-username/prestashop-google-merchant-sync.git
cd prestashop-google-merchant-sync
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure

Copy the example config and fill in your values:

```bash
cp parameters.txt.example parameters.txt
```

Edit `parameters.txt`:

| Key | Description |
|-----|-------------|
| `spreadsheet_feed_id` | Google Sheets ID for the main product feed |
| `spreadsheet_local_inventory_id` | Google Sheets ID for the local inventory feed |
| `store_code` | Your Google Business Profile store code |
| `feed_sheet_name` | Tab name in the feed spreadsheet (default: `Sheet1`) |
| `local_inventory_sheet_name` | Tab name in the inventory spreadsheet (default: `Sheet1`) |
| `service_account_file` | Path to your service account JSON key |
| `shop_base_url` | Your PrestaShop URL (e.g. `https://yourshop.com`) |
| `id_prefix` | Short string prepended to all product IDs (e.g. `ks_`) |
| `tax` | VAT rate as a decimal (e.g. `0.23` for 23%) |
| `batch_size` | Rows per Google Sheets API call (default: `100`) |
| `db_host` | MySQL host |
| `db_name` | PrestaShop database name |
| `db_user` | MySQL username |
| `db_pass` | MySQL password |
| `receiver_email` | Email address for sync notifications |
| `sender_email` | Gmail address used to send notifications |
| `sender_password` | Gmail App Password |

### 4. Add your service account key

Place your Google service account JSON file at the path specified in `service_account_file` (default: `./spreadsheet-service-account-key.json`).

Make sure this file is listed in `.gitignore`.

### 5. Prepare your Google Sheets

Both spreadsheets must already exist and have a header row in row 1. The script writes data starting from row 2 and clears old data on each run.

---

## Running the Script

```bash
python sync.py
```

Logs are written to `logs/sync_YYYYMMDD.log` and mirrored to the console.

### Automate with cron

To run daily at 3:00 AM:

```bash
crontab -e
```

Add:

```
0 3 * * * /usr/bin/python3 /path/to/sync.py >> /path/to/logs/cron.log 2>&1
```

---

## How It Works

```
MySQL (PrestaShop DB)
        │
        ▼
  get_products_from_db()        ← one row per product × attribute combination
        │
        ▼
  process_product_row()         → main feed row (title, price, images, highlights…)
  process_local_inventory_row() → inventory row (stock, price per store)
        │
        ▼
  Google Sheets API (batch append)
        │
        ├── Main Feed Spreadsheet   (Google Merchant product data)
        └── Local Inventory Sheet   (in-store availability)
```

### Product ID generation

Product IDs are generated from the product title + size, normalized to alphanumeric characters only, and prefixed with `id_prefix`:

```
ks_ + normalize("Kask Rowerowy Damski" + "M") → ks_kaskrowerowydarskim
```

This keeps IDs consistent between the main feed and the local inventory feed.

### Description parsing

The script parses structured Polish descriptions written in a common PrestaShop format to extract:

- **Highlights** — feature/technology names (e.g. `Gore-Tex, Boa Fit System`)
- **Product details** — key:value technical specs in Google Merchant format
- **Material** — fabric composition

---

## Requirements

```
mysql-connector-python
google-auth
google-api-python-client
beautifulsoup4
```

Generate `requirements.txt`:

```bash
pip freeze > requirements.txt
```

---

## License

MIT — feel free to adapt this for your own PrestaShop + Google Merchant setup.
