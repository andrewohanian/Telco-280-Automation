from mailer import Mailer
from mailer import Message
from email.utils import formatdate
import secrets


def send_completed_email(router_hostname, router_port, telco_hostname):
    message      = Message(From=secrets.from_email, To=secrets.to_email_list)
    message.Date = formatdate(localtime=True)

    message.Subject = f'{router_hostname} {router_port} successfully configured for {telco_hostname}'
    message.Body    = f'Please update the interface description for {router_hostname} {router_port}.'

    sender = Mailer('localhost', 25)
    sender.send(message)