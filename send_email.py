import secrets
import smtplib
from email.message import EmailMessage

def send_completed_email(router_hostname, router_port, show_run_output, telco_hostname):
    sender = secrets.from_email
    receivers = secrets.to_email_list
    body = f'Please update the interface description for {router_hostname} {router_port} if necessary.\n\n\n'
    body += 'Current interface description:\n\n'
    body += show_run_output

    msg = EmailMessage()
    msg.set_content(body)

    msg['Subject'] = f'{router_hostname} {router_port} successfully configured for {telco_hostname}'
    msg['From'] = sender
    msg['To'] = ', '.join(receivers)


    try:
        smtpObj = smtplib.SMTP('localhost')
        smtpObj.send_message(msg)

    except OSError:
        print("Error: unable to send email")