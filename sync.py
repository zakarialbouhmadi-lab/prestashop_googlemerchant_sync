import logging
import os
import re
import smtplib
import configparser
import mysql.connector
from datetime import datetime
from typing import Dict, Any, List
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from bs4 import BeautifulSoup
from google.oauth2 import service_account
from googleapiclient.discovery import build

# Constants
CONFIG_FILE = 'parameters.txt'
LOG_DIRECTORY = 'logs'


# ─────────────────────────────────────────────
# Configuration & Logging
# ─────────────────────────────────────────────

def load_config():
    """Load configuration from parameters.txt"""
    config = configparser.ConfigParser()
    if not os.path.exists(CONFIG_FILE):
        raise FileNotFoundError(f"{CONFIG_FILE} not found")
    config.read(CONFIG_FILE)
    return config['shop']


def setup_logging():
    """Initialize file and console logger"""
    if not os.path.exists(LOG_DIRECTORY):
        os.makedirs(LOG_DIRECTORY)

    logger = logging.getLogger('shop_sync')
    logger.setLevel(logging.INFO)

    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    log_file = os.path.join(LOG_DIRECTORY, f'sync_{datetime.now().strftime("%Y%m%d")}.log')
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


# ─────────────────────────────────────────────
# Email Notification
# ─────────────────────────────────────────────

def send_email_notification(receiver_email, sender_email, sender_password, success, error_message=None):
    """Send email notification about script execution status"""
    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = receiver_email

    if success:
        msg['Subject'] = "Product Sync - Success"
        body = "INFO: The product synchronization script completed successfully."
    else:
        msg['Subject'] = "Product Sync - Error"
        body = f"ERROR: The product synchronization script encountered an error:\n\n{error_message}"

    msg.attach(MIMEText(body, 'plain'))

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender_email, sender_password)
            server.send_message(msg)
        return True
    except Exception as e:
        return False


# ─────────────────────────────────────────────
# Google Sheets
# ─────────────────────────────────────────────

def setup_google_sheets(service_account_file):
    """Initialize Google Sheets API service"""
    SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
    credentials = service_account.Credentials.from_service_account_file(
        service_account_file, scopes=SCOPES)
    return build('sheets', 'v4', credentials=credentials)


# ─────────────────────────────────────────────
# Text & Data Processing Helpers
# ─────────────────────────────────────────────

def clean_html(html_text):
    """Strip HTML tags and normalize whitespace, preserving paragraph structure"""
    if not html_text:
        return ""

    soup = BeautifulSoup(html_text, 'html.parser')

    for p in soup.find_all('p'):
        if not p.get_text(strip=True):
            p.decompose()

    paragraphs = []
    for p in soup.find_all('p'):
        text = re.sub(r'\s+', ' ', p.get_text(separator=' ')).strip()
        if text:
            paragraphs.append(text)

    return '\n'.join(paragraphs)


def format_unity(unity):
    """Normalize unit pricing measure (e.g. 'za kg' → '1kg')"""
    if not unity:
        return ''
    unity = re.sub(r'^za\s+', '', unity.strip(), flags=re.IGNORECASE).lower()
    if unity and unity[0].isalpha():
        unity = '1' + unity
    return unity


def format_price(price):
    """Format a float price to 'XX.XX PLN' string"""
    if price <= 0:
        return ""
    return f"{float(price):.2f} PLN"


def apply_tax(price, tax_rate):
    """Return price with VAT applied"""
    return price + (price * tax_rate)


def apply_promotion(price, reduction, reduction_type):
    """Return discounted price based on reduction type (percentage or amount)"""
    if not reduction or not reduction_type:
        return price
    if reduction_type == 'percentage':
        return price * (1 - float(reduction))
    return price - float(reduction)


def split_description_into_2_paragraphs(clean_description):
    """Split description into a general intro and a technical details section"""
    separators = ['Parametry produktu:', 'Technologie:', 'Cechy:']
    first_newline = clean_description.find('\n')
    if first_newline == -1:
        return [clean_description, '']
    clean_description = clean_description[first_newline + 1:]
    for sep in separators:
        index = clean_description.find(sep)
        if index != -1:
            return [clean_description[:index - 1], clean_description[index:]]
    return [clean_description, '']


def parse_highlights_and_details_from_description(clean_2nd_paragraph):
    """
    Parse the technical section of a product description into:
    - highlights: feature/technology names (comma-separated)
    - details:    key:value pairs (Google Merchant product_detail format)
    """
    DETAILS_TO_IGNORE = [
        'kod produktu', 'kod producenta', 'kod katalogowy', 'rocznik',
        'numer katalogowy', 'kolor', 'materiał', 'skład materiału',
        'rozmiar', 'skład', 'rozmiary'
    ]
    lines = clean_2nd_paragraph.split('\n')
    highlights = ''
    details = ''

    for line in lines:
        line = line.replace('–', '-').strip()
        split_detail = line.split(':')

        if len(split_detail) > 1:
            if split_detail[1] == '':          # Section title — skip
                continue
            if split_detail[0].lower().strip() not in DETAILS_TO_IGNORE:
                details += (
                    ':' + split_detail[0].split('-')[0].replace(',', ' ').strip()
                    + ':' + split_detail[1].split('-')[0].strip().replace(',', ' ') + ','
                )
            continue

        split_highlight = line.split(' - ')
        if len(split_highlight) > 1:
            highlights += split_highlight[0].strip() + ','
            continue

        highlights += line + ','

    highlights = highlights.rstrip(',')
    details = details.rstrip(',')

    return [highlights.title(), details]


def parse_material(text):
    """Extract material/composition info from description text"""
    for pattern in ['Materiał', 'Skład materiału']:
        match = re.search(rf"{pattern}:\s*(.*)", text, re.IGNORECASE)
        if match:
            result = (match.group(1)
                      .replace(',', '/').replace(';', '/')
                      .replace('/ ', '/').replace(' /', '/').strip())
            return result.rstrip('/')
    return ''


def parse_gender_and_age(gender):
    """Map Polish gender string to Google Merchant gender + age_group values"""
    GENDER_AGE_MAP = {
        'unisex':  ['unisex', 'adult'],
        'męska':   ['male',   'adult'],
        'damska':  ['female', 'adult'],
        'junior':  ['',       'kids'],
        'baby':    ['',       'kids'],
    }
    cleaned = gender.strip().lower() if gender else ''
    return GENDER_AGE_MAP.get(cleaned, ['', ''])


def parse_details_from_attributes(text):
    """Parse pipe-separated attribute string into a structured dict"""
    txt = text.replace('\n', '').strip()
    attributes_dict = {'kolor': '', 'rozmiar': '', 'płeć': '', 'details': ''}
    if not txt:
        return attributes_dict

    for kv in txt.split('|'):
        split_kv = kv.split(':')
        if len(split_kv) > 1:
            key = split_kv[0].lower().strip()
            if key in attributes_dict:
                attributes_dict[key] = split_kv[1]
            else:
                attributes_dict['details'] += (
                    ':' + split_kv[0].strip().replace(',', ' ')
                    + ':' + split_kv[1].strip().replace(',', ' ') + ','
                )

    attributes_dict['details'] = attributes_dict['details'].rstrip(',')
    return attributes_dict


def generate_product_link(shop_base_url, category_link, id_product, id_product_attribute, link_rewrite):
    """Build the canonical PrestaShop product URL"""
    return f"{shop_base_url}/{category_link}/{id_product}-{id_product_attribute}-{link_rewrite}.html"


def generate_images_links(shop_base_url, image_ids, link_rewrite):
    """
    Build main image URL and additional image URLs from comma-separated image IDs.
    Returns [main_image_link, additional_images_csv].
    """
    if not image_ids or image_ids == "None":
        return ["", ""]

    all_ids = image_ids.split(',')
    if not all_ids or not all_ids[0]:
        return ["", ""]

    main_image_link = f"{shop_base_url}/{all_ids[0]}-product_zoom/{link_rewrite}.jpg"

    additional = ','.join(
        f"{shop_base_url}/{img_id}-product_zoom/{link_rewrite}.jpg"
        for img_id in all_ids[1:]
    )
    return [main_image_link, additional]


# ─────────────────────────────────────────────
# Database
# ─────────────────────────────────────────────

def get_products_from_db(db_config):
    """
    Fetch all active product variants from the PrestaShop database.
    Returns a list of dicts, one per product/attribute combination.
    """
    conn = mysql.connector.connect(
        host=db_config['db_host'],
        user=db_config['db_user'],
        password=db_config['db_pass'],
        database=db_config['db_name']
    )
    cursor = conn.cursor(dictionary=True)

    query = """
    SELECT
        p.id_product, pa.id_product_attribute, pl.name AS title,
        p.price, p.unity, p.unit_price, pl.link_rewrite,
        pl.description, pa.reference, pa.ean13, m.name AS brand,
        sp.reduction, sp.reduction_type, sa.quantity, cl.id_category,
        cl.link_rewrite AS category_link,
        GROUP_CONCAT(CONCAT(agl.name, ': ', al.name) SEPARATOR ' | ') AS attributes,
        COALESCE(
            (SELECT GROUP_CONCAT(pai.id_image)
             FROM ps_product_attribute_image pai
             WHERE pai.id_product_attribute = pa.id_product_attribute),
            (SELECT GROUP_CONCAT(i.id_image)
             FROM ps_image i
             WHERE i.id_product = p.id_product)
        ) AS image_ids
    FROM ps_product_attribute pa
    INNER JOIN ps_product p              ON pa.id_product = p.id_product
    LEFT  JOIN ps_product_lang pl        ON pl.id_product = p.id_product
    LEFT  JOIN ps_manufacturer m         ON m.id_manufacturer = p.id_manufacturer
    LEFT  JOIN ps_specific_price sp      ON sp.id_product = p.id_product
    LEFT  JOIN ps_stock_available sa     ON sa.id_product_attribute = pa.id_product_attribute
    LEFT  JOIN ps_category_lang cl       ON cl.id_category = p.id_category_default
    LEFT  JOIN ps_product_attribute_combination pac
                                         ON pac.id_product_attribute = pa.id_product_attribute
    LEFT  JOIN ps_attribute a            ON a.id_attribute = pac.id_attribute
    LEFT  JOIN ps_attribute_lang al      ON al.id_attribute = a.id_attribute
    LEFT  JOIN ps_attribute_group_lang agl
                                         ON agl.id_attribute_group = a.id_attribute_group
    WHERE p.active = 1
    GROUP BY p.id_product, pa.id_product_attribute
    ORDER BY sp.reduction ASC
    """

    cursor.execute(query)
    products = cursor.fetchall()
    cursor.close()
    conn.close()
    return products


# ─────────────────────────────────────────────
# Row Processors
# ─────────────────────────────────────────────

def process_product_row(row, shop_base_url, store_code, id_prefix, tax_rate):
    """Transform a raw DB row into a Google Merchant main feed row"""
    product_link = generate_product_link(
        shop_base_url, row['category_link'],
        row['id_product'], row['id_product_attribute'], row['link_rewrite']
    )
    images_links = generate_images_links(shop_base_url, row['image_ids'], row['link_rewrite'])

    clean_description = clean_html(row['description'])
    paragraphs = split_description_into_2_paragraphs(clean_description)
    highlights_and_details = parse_highlights_and_details_from_description(paragraphs[1])

    attributes_dict = parse_details_from_attributes(row['attributes'])

    regular_price = apply_tax(float(row['price']), tax_rate)
    regular_price_str = format_price(regular_price)

    sale_price_str = ''
    if row['reduction'] and float(row['reduction']) > 0:
        discounted = apply_promotion(float(row['price']), row['reduction'], row['reduction_type'])
        sale_price_str = format_price(apply_tax(discounted, tax_rate))

    gender_age = parse_gender_and_age(attributes_dict['płeć'])

    product_id = id_prefix + re.sub(
        r'[^a-zA-Z0-9]', '',
        f'{row["title"].lower()}{attributes_dict["rozmiar"].lower()}'
    )

    detail_parts = [attributes_dict['details'], highlights_and_details[1]]
    separator = ', ' if all(len(p) > 1 for p in detail_parts) else ''
    product_detail = separator.join(filter(None, detail_parts))

    return {
        'id': product_id,
        'store_code': store_code,
        'title': row['title'].title().strip(),
        'description': paragraphs[0],
        'availability': 'in_stock' if int(row['quantity']) > 0 else 'out_of_stock',
        'availability date': '',
        'expiration date': '',
        'link': product_link,
        'mobile link': product_link,
        'image link': images_links[0],
        'price': regular_price_str,
        'sale price': sale_price_str,
        'sale price effective date': '',
        'identifier exists': 'yes' if row['ean13'] or row['reference'] else 'no',
        'gtin': row['ean13'],
        'mpn': row['reference'] if row['reference'] and row['reference'] != row['ean13'] else '',
        'brand': row['brand'].title() if row['brand'] else '',
        'product highlight': highlights_and_details[0],
        'product detail': product_detail,
        'additional image link': images_links[1],
        'condition': 'new',
        'adult': 'no',
        'color': attributes_dict['kolor'].strip().title().replace(' ', '/'),
        'size': attributes_dict['rozmiar'],
        'size type': '',
        'size system': '',
        'gender': gender_age[0],
        'material': parse_material(paragraphs[1]),
        'pattern': '',
        'age group': gender_age[1],
        'multipack': '',
        'is bundle': 'no',
        'unit pricing measure': format_price(float(row['unit_price'])),
        'unit pricing base measure': format_unity(row['unity']),
        'energy efficiency class': '',
        'min energy efficiency class': '',
        'max energy efficiency class': '',
        'item group id': '',
        'sell on google quantity': '',
    }


def process_local_inventory_row(row, store_code, id_prefix, tax_rate):
    """Transform a raw DB row into a Google Merchant local inventory feed row"""
    regular_price = apply_tax(float(row['price']), tax_rate)
    regular_price_str = format_price(regular_price)

    sale_price_str = ''
    if row['reduction'] and float(row['reduction']) > 0:
        discounted = apply_promotion(float(row['price']), row['reduction'], row['reduction_type'])
        sale_price_str = format_price(apply_tax(discounted, tax_rate))

    attributes_dict = parse_details_from_attributes(row['attributes'])
    product_id = id_prefix + re.sub(
        r'[^a-zA-Z0-9]', '',
        f'{row["title"].lower()}{attributes_dict["rozmiar"].lower()}'
    )

    return {
        'id': product_id,
        'store_code': store_code,
        'quantity': int(row['quantity']),
        'price': regular_price_str,
        'sale_price': sale_price_str,
        'sale_price_effective_date': '',
        'availability': 'in_stock' if int(row['quantity']) > 0 else 'out_of_stock',
    }


# ─────────────────────────────────────────────
# Main Sync Logic
# ─────────────────────────────────────────────

def run_sync():
    """Fetch products from the DB and upload them to Google Sheets"""
    config = load_config()
    logger = setup_logging()
    logger.info('Starting product sync process')

    try:
        shop_base_url              = config['shop_base_url']
        store_code                 = config['store_code']
        feed_sheet_name            = config['feed_sheet_name']
        feed_spreadsheet_id        = config['spreadsheet_feed_id']
        local_inv_sheet_name       = config['local_inventory_sheet_name']
        local_inv_spreadsheet_id   = config['spreadsheet_local_inventory_id']
        id_prefix                  = config['id_prefix']
        batch_size                 = int(config['batch_size'])
        tax_rate                   = float(config['tax'])
        service_account_file       = config['service_account_file']

        db_config = {
            'db_host': config['db_host'],
            'db_name': config['db_name'],
            'db_user': config['db_user'],
            'db_pass': config['db_pass'],
        }

        receiver_email   = config['receiver_email']
        sender_email     = config['sender_email']
        sender_password  = config['sender_password']

        # ── Fetch products ──────────────────────────────────────────────────
        logger.info('Fetching products from database...')
        products = get_products_from_db(db_config)
        total = len(products)
        logger.info(f'Found {total} active product variants')

        # ── Google Sheets setup ─────────────────────────────────────────────
        logger.info('Connecting to Google Sheets...')
        service = setup_google_sheets(service_account_file)
        logger.info('Google Sheets connected.')

        # ── Clear old data ──────────────────────────────────────────────────
        for spreadsheet_id, sheet_name, label in [
            (feed_spreadsheet_id,      feed_sheet_name,      'main feed'),
            (local_inv_spreadsheet_id, local_inv_sheet_name, 'local inventory'),
        ]:
            logger.info(f'Clearing {label} sheet...')
            service.spreadsheets().values().clear(
                spreadsheetId=spreadsheet_id,
                range=f'{sheet_name}!A2:ZZ'
            ).execute()
            logger.info(f'{label.capitalize()} sheet cleared.')

        # ── Process & upload rows ───────────────────────────────────────────
        feed_batch, inventory_batch = [], []

        def flush_batch(batch, spreadsheet_id, sheet_name, label):
            if not batch:
                return
            logger.info(f'Uploading {len(batch)} rows to {label}...')
            service.spreadsheets().values().append(
                spreadsheetId=spreadsheet_id,
                range=f'{sheet_name}!A2',
                valueInputOption='RAW',
                insertDataOption='INSERT_ROWS',
                body={'values': batch}
            ).execute()
            logger.info(f'Batch uploaded to {label}.')

        for index, row in enumerate(products, 1):
            logger.info(f'Processing variant {index}/{total}...')

            feed_batch.append(list(process_product_row(
                row, shop_base_url, store_code, id_prefix, tax_rate).values()))
            inventory_batch.append(list(process_local_inventory_row(
                row, store_code, id_prefix, tax_rate).values()))

            if len(feed_batch) >= batch_size:
                flush_batch(feed_batch, feed_spreadsheet_id, feed_sheet_name, 'main feed')
                feed_batch = []
            if len(inventory_batch) >= batch_size:
                flush_batch(inventory_batch, local_inv_spreadsheet_id, local_inv_sheet_name, 'local inventory')
                inventory_batch = []

        # Flush remaining rows
        flush_batch(feed_batch,      feed_spreadsheet_id,      feed_sheet_name,      'main feed')
        flush_batch(inventory_batch, local_inv_spreadsheet_id, local_inv_sheet_name, 'local inventory')

        logger.info('Sync completed successfully.')

        if send_email_notification(receiver_email, sender_email, sender_password, success=True):
            logger.info('Success notification sent.')
        else:
            logger.warning('Could not send success notification.')

        return True

    except Exception as e:
        error_message = str(e)
        logger.error(f'Sync failed: {error_message}')
        send_email_notification(receiver_email, sender_email, sender_password,
                                success=False, error_message=error_message)
        return False


# ─────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────

if __name__ == "__main__":
    start = datetime.now()
    print(f"Starting product sync at {start}")
    success = run_sync()
    end = datetime.now()
    print(f"Finished at {end} — duration: {end - start}")
    exit(0 if success else 1)
