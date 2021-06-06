import requests
import datetime
import logging
import configparser
import math
import calendar

config = configparser.ConfigParser()
config.read('config.ini')
api_key = config['user']['api_key']
user_id = config['user']['user_id']
transfer_category_id = config['user']['transfer_category_id']
checking_account_id = config['user']['checking_account_id']
mortgage_account_id = config['mortgage_account']['account_id']
mortgage_interest_category_id = config['mortgage_account']['interest_category_id']
mortgage_interest_rate = config.getfloat('mortgage_account', 'interest_rate')
mortgage_interest_payee = config['mortgage_account']['interest_payee']
mortgage_escrow_account_id = config['mortgage_account']['escrow_account_id']
mortgage_escrow_amount = config.getfloat('mortgage_account', 'escrow_amount')
mortgage_pmi_category_id = config['mortgage_account']['pmi_category_id']
mortgage_pmi_amount = config.getfloat('mortgage_account', 'pmi_amount')
studentloan_account_id = config['studentloan_account']['account_id']
studentloan_interest_category_id = config['studentloan_account']['interest_category_id']
studentloan_interest_rate = config.getfloat('studentloan_account', 'interest_rate')
studentloan_interest_payee = config['studentloan_account']['interest_payee']
carloan_account_id = config['carloan_account']['account_id']
carloan_interest_category_id = config['carloan_account']['interest_category_id']
carloan_interest_rate = config.getfloat('carloan_account', 'interest_rate')
carloan_interest_payee = config['carloan_account']['interest_payee']

max_transfer_delay_days = 5

base_url = "https://api.pocketsmith.com/v2/"


def main():
  add_mortgage_loan_transactions()
  add_studentloan_loan_transactions()
  add_carloan_loan_transactions()


def add_mortgage_loan_transactions():
  search_term='mortgage payment'
  logging.info(f'Searching for "{search_term}" transactions...')
  sent_payments = find_transactions(search_term, checking_account_id, num_days=90)
  for txn in sent_payments:
    logging.info('  %s\t%s\t%s', txn['date'], txn['amount'], txn['payee'])
  assert 1 <= len(sent_payments) and len(sent_payments) <= 3
  for txn in reversed(sent_payments):
    add_single_loan_transaction(
        txn,
        mortgage_account_id,
        mortgage_interest_rate,
        mortgage_interest_category_id,
        mortgage_interest_payee,
        post_add_transaction_handler=add_mortgage_escrow_and_pmi_transactions,
    )

def add_mortgage_escrow_and_pmi_transactions(date):
  add_transfer(
    mortgage_account_id,
    f'{mortgage_interest_payee} Mortgage',
    mortgage_escrow_account_id,
    f'{mortgage_interest_payee} Escrow',
    date,
    mortgage_escrow_amount,
  )
  add_transaction(
    mortgage_account_id,
    date,
    -mortgage_pmi_amount,
    mortgage_interest_payee,
    mortgage_pmi_category_id,
  )

def add_studentloan_loan_transactions():
  search_term='student loan payment'
  logging.info(f'Searching for "{search_term}" transactions...')
  sent_payments = find_transactions(search_term, checking_account_id, num_days=90)
  for txn in sent_payments:
    logging.info('  %s\t%s\t%s', txn['date'], txn['amount'], txn['payee'])
  assert 1 <= len(sent_payments) and len(sent_payments) <= 3
  for txn in reversed(sent_payments):
    add_single_loan_transaction(
        txn,
        studentloan_account_id,
        studentloan_interest_rate,
        studentloan_interest_category_id,
        studentloan_interest_payee,
        interest_type=studentloan_interest,
    )

def add_carloan_loan_transactions():
  search_term='car loan payment'
  logging.info(f'Searching for "{search_term}" transactions...')
  sent_payments = find_transactions(search_term, checking_account_id, num_days=90)
  for txn in sent_payments:
    logging.info('  %s\t%s\t%s', txn['date'], txn['amount'], txn['payee'])
  assert 1 <= len(sent_payments) and len(sent_payments) <= 3
  for txn in reversed(sent_payments):
    add_single_loan_transaction(
        txn,
        carloan_account_id,
        carloan_interest_rate,
        carloan_interest_category_id,
        carloan_interest_payee,
        interest_type=carloan_interest,
    )

def mortgage_interest(balance, date, interest_rate):
  return balance * interest_rate/100 / 12

def studentloan_interest(balance, date, interest_rate):
  daily_interest = balance * interest_rate/100 / get_days_in_year(date)
  daily_interest = truncate_digits(daily_interest, 4)
  monthly_interest = daily_interest * get_days_in_month(date)
  monthly_interest = truncate_digits(monthly_interest, 2)
  return monthly_interest

def carloan_interest(balance, date, interest_rate):
  return studentloan_interest(balance, date, interest_rate)

def add_single_loan_transaction(sent_payment, loan_account_id, interest_rate,
    interest_category_id, interest_payee, interest_type=mortgage_interest,
    post_add_transaction_handler=None):
  date = parse_date(sent_payment['date'])
  max_recv_date = date + datetime.timedelta(days=max_transfer_delay_days)
  logging.info(f'Checking loan account around {date}...')
  transactions = find_transactions(
    '',
    loan_account_id,
    num_days=60,
    end_date=max_recv_date,
  )
  assert len(transactions) > 0
  last_txn = transactions[0]
  last_txn_date = parse_date(last_txn['date'])
  for txn in transactions:
    assert(parse_date(txn['date']) <= last_txn_date)
  balance = last_txn['closing_balance']
  logging.info(
    '  %s\t%s\t%s\t%s',
    last_txn['date'],
    last_txn['amount'],
    last_txn['category']['title'],
    f'balance={balance}',
  )
  if abs((date - last_txn_date).days) <= max_transfer_delay_days:
    logging.info('  Nothing to do here.')
    return
  add_transaction(
    loan_account_id,
    date,
    -sent_payment['amount'],
    sent_payment['transaction_account']['name'],
    is_transfer=True,
    category_id=sent_payment['category']['id'],
  )
  monthly_interest = interest_type(balance, last_txn_date, interest_rate)
  add_transaction(
    loan_account_id,
    date,
    monthly_interest,
    interest_payee,
    category_id=interest_category_id,
  )
  if post_add_transaction_handler is not None:
    post_add_transaction_handler(date)

def get_days_in_month(date):
  return calendar.monthrange(date.year, date.month)[1]

def get_days_in_year(date):
  return 1 + (datetime.datetime(date.year, 12, 31) - datetime.datetime(date.year, 1, 1)).days

def truncate_digits(value, digits):
  pow10 = 10**digits
  return int(value * pow10) / pow10

def send_request(path, method="GET", **kwargs):
  url = base_url + path
  headers = {
    "Accept": "application/json",
    "X-Developer-Key": api_key
  }
  response = requests.request(method, url, headers=headers, **kwargs)
  response_body = response.json()
  if "error" in response_body:
    error = response_body["error"]
    raise Exception(f"Request error ({method} {path}): {error}")
  response.raise_for_status()
  return response_body

def get_current_user_id():
  response = send_request('me')
  return response['id']

def get_accounts():
  return send_request(f'users/{user_id}/transaction_accounts')

def print_accounts():
  for acct in get_accounts():
    logging.info("%s\t%s", acct['id'], acct['name'])

def find_transactions(search_term, account_id, num_days, end_date=datetime.datetime.today()):
  start_date = end_date - datetime.timedelta(days=num_days)
  return send_request(
    f'transaction_accounts/{account_id}/transactions',
    params={
      'search': search_term,
      'start_date': start_date.strftime('%Y-%m-%d'),
      'end_date': end_date.strftime('%Y-%m-%d'),
    })

def add_transfer(from_account_id, from_account_name, to_account_id, to_account_name, date, amount):
  add_transaction(from_account_id, date, -amount, to_account_name, transfer_category_id, True)
  add_transaction(to_account_id, date, amount, from_account_name, transfer_category_id, True)

def add_transaction(account_id, date, amount, payee, category_id=None, is_transfer=False):
  logging.warning('ADDING TRANSACTION:')
  logging.warning(f'  account_id: {account_id}')
  logging.warning(f'        date: {date}')
  logging.warning(f'      amount: {amount}')
  logging.warning(f'       payee: {payee}')
  logging.warning(f' category_id: {category_id}')
  logging.warning(f' is_transfer: {is_transfer}')
  send_request(
    f'transaction_accounts/{account_id}/transactions',
    method='POST',
    json={
      'payee': payee,
      'amount': amount,
      'date': date.strftime('%Y-%m-%d'),
      'is_transfer': is_transfer,
      'category_id': category_id,
    })

def init_logging():
  logging.basicConfig(
      level=logging.DEBUG,
      format='%(asctime)s %(levelname)-8s %(message)s',
      datefmt='%Y-%m-%d %H:%M:%S',
      filename='add_loan_transactions.log',
  )
  console = logging.StreamHandler()
  console.setLevel(logging.INFO)
  formatter = logging.Formatter('%(levelname)-8s %(message)s')
  console.setFormatter(formatter)
  logging.getLogger('').addHandler(console)

def parse_date(text):
  return datetime.datetime.strptime(text, '%Y-%m-%d')

init_logging()
main()
