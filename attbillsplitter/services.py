#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""Service that aggregate monthly wireless charges for each line in account.
"""

import configparser
import datetime as dt
import logging
import sys
import peewee as pw
from twilio.rest import TwilioRestClient
from attbillsplitter.models import (
    User, ChargeCategory, ChargeType, BillingCycle, Charge, MonthlyBill, db
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
ch = logging.FileHandler('notif_history.log')
ch.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
ch.setFormatter(formatter)
logger.addHandler(ch)


def print_wireless_monthly_summary(month, year=None):
    """Get wireless monthly summary for all lines. Results will be printed
    to console.

    :param month: month (1 - 12) of the end date of billing cycle
    :type month: int
    :param year: year of the end of of billing cycle. Default to current year
    :type year: int
    :returns: None
    """
    # year value default to current year
    year = year or dt.date.today().year
    if not BillingCycle.select().where(
        db.extract_date('month', BillingCycle.end_date) == month,
        db.extract_date('year', BillingCycle.end_date) == year
    ).exists():
        print('No charge summary found for {}/{}. Please split the '
              'bill first'.format(year, month))
        return

    bc = BillingCycle.select().where(
        db.extract_date('month', BillingCycle.end_date) == month,
        db.extract_date('year', BillingCycle.end_date) == year
    ).get()
    print('--------------------------------------------------------------')
    print('    Charge Summary for Billing Cycle {}'.format(bc.name))
    print('--------------------------------------------------------------')
    query = (
        User
        .select(User.name,
                User.number,
                MonthlyBill.total)
        .join(MonthlyBill)
        .where(MonthlyBill.billing_cycle_id == bc.id)
        .naive()
    )
    wireless_total = 0
    for user in query.execute():
        print('    {:^18s} ({})      Total: {:.2f}'.format(
            user.name, user.number, user.total
        ))
        wireless_total += user.total
    print('--------------------------------------------------------------')
    print('{:>47}: {:.2f}'.format('Wireless Total', wireless_total))


def print_wireless_monthly_details(month, year=None):
    """Get wireless monthly details for all lines. Results will be printed
    to console.

    :param month: month (1 - 12) of the end date of billing cycle
    :type month: int
    :param year: year of the end of of billing cycle. Default to current year
    :type year: int
    :returns: None
    """
    # year value default to current year
    year = year or dt.date.today().year
    if not BillingCycle.select().where(
        db.extract_date('month', BillingCycle.end_date) == month,
        db.extract_date('year', BillingCycle.end_date) == year
    ).exists():
        print('No charge summary found for {}/{}. Please split the '
              'bill first'.format(year, month))
        return

    bc = BillingCycle.select().where(
        db.extract_date('month', BillingCycle.end_date) == month,
        db.extract_date('year', BillingCycle.end_date) == year
    ).get()
    query = (
        User
        .select(User.id,
                User.name,
                User.number,
                ChargeType.text.alias('charge_type'),
                pw.fn.SUM(Charge.amount).alias('total'))
        .join(Charge)
        .join(BillingCycle)
        .switch(Charge)
        .join(ChargeType)
        .join(ChargeCategory)
        .where(BillingCycle.id == bc.id,
               ChargeCategory.category == 'wireless')
        .group_by(User, BillingCycle, ChargeType)
        .order_by(User.id)
        .naive()
    )
    current_user_num = ''
    current_user_total = 0
    wireless_total = 0
    for user in query.execute():
        if user.number != current_user_num:
            if current_user_total:
                print('      - {:40}   {:.2f}\n'.format('Total',
                                                        current_user_total))
                wireless_total += current_user_total
            current_user_num = user.number
            current_user_total = 0
            print('    {} ({})'.format(user.name, user.number))
        print('      - {:40}   {:.2f}'.format(user.charge_type, user.total))
        current_user_total += user.total
    if current_user_total:
        print('      - {:40}   {:.2f}\n'.format('Total', current_user_total))
    print('{:>48}: {:.2f}'.format('Wireless Total', wireless_total))


def notify_users_monthly_details(message_client, payment_msg, month,
                                 year=None):
    """Calculate monthly charge details for users and notify them.

    :param message_client: a message client to send text message
    :type message_client: MessageClient
    :param payment_message: text appended to charge details so that your
        users know how to pay you.
    :param type: str
    :param month: month (1 - 12) of the end date of billing cycle
    :type month: int
    :param year: year of the end of of billing cycle. Default to current year
    :type year: int
    :returns: None
    """
    # year value default to current year
    year = year or dt.date.today().year
    if not BillingCycle.select().where(
        db.extract_date('month', BillingCycle.end_date) == month,
        db.extract_date('year', BillingCycle.end_date) == year
    ).exists():
        print('No charge summary found for {}/{}. Please split the '
              'bill first'.format(year, month))
        return

    bc = BillingCycle.select().where(
        db.extract_date('month', BillingCycle.end_date) == month,
        db.extract_date('year', BillingCycle.end_date) == year
    ).get()
    query = (
        User
        .select(User.id,
                User.name,
                User.number,
                ChargeType.text.alias('charge_type'),
                pw.fn.SUM(Charge.amount).alias('total'))
        .join(Charge)
        .join(BillingCycle)
        .switch(Charge)
        .join(ChargeType)
        .join(ChargeCategory)
        .where(BillingCycle.id == bc.id,
               ChargeCategory.category == 'wireless')
        .group_by(User, BillingCycle, ChargeType)
        .order_by(User.id)
        .naive()
    )
    current_user_num = -1
    current_user_total = 0
    messages = {}
    message = ''
    for user in query.execute():
        if user.number != current_user_num:
            if current_user_total:
                message += '  - {:30} {:.2f} \U0001F911\n'.format(
                    'Total', current_user_total
                )
                messages[current_user_num] = message
            current_user_num = user.number
            current_user_total = 0
            message = ('Hi {} ({}),\nYour AT&T Wireless Charges '
                       'for {}:\n'.format(user.name, user.number, bc.name))
        message += '  - {:30} {:.2f}\n'.format(user.charge_type, user.total)
        current_user_total += user.total
    if current_user_total:
        message += '  - {:30} {:.2f} \U0001F911\n'.format('Total',
                                                          current_user_total)
    # print message for user to confirm
    for num, msg in messages.items():
        print(num)
        print(msg)
        notify = input('Notify (y/n)? ')
        if notify in ('y', 'Y', 'yes', 'Yes', 'YES'):
            body = '{}\n{}'.format(msg, payment_msg)
            message_client.send_message(body=body, to=num)
            logger.info('%s charge details sent to %s, body:\n%s',
                        bc.name, num, msg)
            print('Message send to {}\n'.format(num))


class MessageClient(object):
    """Twilio message client that sends text message to users."""
    def __init__(self, number, account_sid, auth_token):
        """
        :param number: twilio number (+11234567890)
        :type number: str
        :param account_sid: twilio account security identifier
        :type account_sid: str
        :param auth_token: twilio authentication token
        :type auth_token: str
        """
        self.number = number
        self.twilio_client = TwilioRestClient(account_sid, auth_token)

    def send_message(self, body, to):
        """Send message body from self.number to a phone number.

        :param body: message body to send
        :type body: str
        :param to: number to send message to (123-456-789)
        :type to: str
        :returns None
        """
        self.twilio_client.messages.create(body=body, to=to, from_=self.number)


def run_print_summary():
    """Take arguments from command line and run print_wireless_monthly_summary
    """
    month = int(sys.argv[1])
    year = int(sys.argv[2]) if len(sys.argv) == 3 else None
    print_wireless_monthly_summary(month, year)


def run_print_details():
    """Take arguments from command line and run print_wireless_monthly_details
    """
    month = int(sys.argv[1])
    year = int(sys.argv[2]) if len(sys.argv) == 3 else None
    print_wireless_monthly_details(month, year)


def run_notify_users():
    """Take arguments from command line and run notify_users_monthly_details
    """
    config = configparser.ConfigParser()
    config_path = sys.argv[1]
    config.read(config_path)
    twilio_conf = config['twilio']
    number = twilio_conf['number']
    if number == 'your_twilio_number':
        print('Please add you twilio number in config.ini. '
              'You can get one for free at https://www.twilio.com/')
    account_sid = twilio_conf['account_sid']
    if account_sid == 'your_twilio_account_sid':
        print('Please add you twilio account_sid in config.ini.')
    auth_token = twilio_conf['auth_token']
    if auth_token == 'your_twilio_auth_token':
        print('Please add you twilio auth_token in config.ini.')
    payment_msg = twilio_conf['payment_msg']
    mc = MessageClient(number, account_sid, auth_token)
    month = int(sys.argv[2])
    year = int(sys.argv[3]) if len(sys.argv) == 4 else None
    notify_users_monthly_details(mc, payment_msg, month, year)
