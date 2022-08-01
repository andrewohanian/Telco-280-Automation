import pexpect
import sys
import json
import os
import logging
import ipaddress
import time
from get_and_reserve_inventory_mgmt_ip_from_ipam import get_mgmt_ip_from_inventory_number
from get_and_reserve_inventory_mgmt_ip_from_ipam import change_mgmt_ip_descriptions
from generate_config import generate_280_config
from configure_core_mgmt_ip import find_core_port_from_pon
from configure_core_mgmt_ip import configure_router
from send_email import send_completed_email
import secrets

logging.basicConfig(
    filename='files/log.txt',
    level=logging.DEBUG,
    format="%(asctime)s %(message)s"
)

with open(f'{secrets.path_to_config_parameters_file}/CONFIG_PARAMETERS.json', 'r') as config_parameters_file:
    config_parameters = json.load(config_parameters_file)
    logging.info(f'Running for config_parameters: {config_parameters}')

#Get Mgmt IP from inventory number
logging.info(f'Looking up mgmt IP for inventory number {config_parameters["INVENTORY_NUMBER"]}')
mgmt_ip = get_mgmt_ip_from_inventory_number(config_parameters["INVENTORY_NUMBER"])
logging.info(f'Found mgmt IP from lookup up inventory number in IPAM: {mgmt_ip}')
mgmt_default_gateway_ip = str(ipaddress.ip_address(mgmt_ip) -1)
logging.info(f'Calculated mgmt default gateway IP: {mgmt_default_gateway_ip}')

#Find core port, get SNMP details from the core router, and configure the core port if necessary
core_port_details = find_core_port_from_pon(config_parameters)
logging.info(f'Found core port details using PON: {core_port_details}')

if core_port_details == None:
    print('Could not find the core port from the given PONs. Exiting script...')
    sys.exit(1)

config_parameters['SNMP_LOCATION'] = core_port_details['router_location']
logging.info(f'Found SNMP location from core port details: {config_parameters["SNMP_LOCATION"]}')

if core_port_details['configured'] == True:
    print(f'Core interface {core_port_details["port_name"]} on {core_port_details["router_hostname"]} is already configured\n')
    logging.info(f'Core interface {core_port_details["port_name"]} on {core_port_details["router_hostname"]} is already configured')

if core_port_details['configured'] == False:
    logging.info(f'Configuring the core router interface...')
    configure_router(router_mgmt_ip = core_port_details['router_mgmt_ip'], 
                    router_os       = core_port_details['router_os'], 
                    port_name       = core_port_details['port_name'], 
                    pon             = core_port_details['pon'], 
                    router_hostname = core_port_details['router_hostname'], 
                    mgmt_default_gateway_ip = mgmt_default_gateway_ip)

#Attempt to ping mgmt IP
logging.info(f'Pinging {mgmt_ip}')
#Ping twice first, to allow for ARP resolution
response = os.system(f'ping -c 2 {mgmt_ip}')
time.sleep(5)
response = os.system(f'ping -c 1 {mgmt_ip}')
if response != 0:
    print(f'Could not ping the Telco at {mgmt_ip}. Aborting script. Please troubleshoot connectivity and then try again.')
    logging.critical(f'Ping failed with response {response}. Exiting script')
    sys.exit(1)

print(f'Ping to {mgmt_ip} successful. Configuring Telco via SSH...\n')
logging.info(f'Ping to {mgmt_ip} successful')

hostname = f'STRATUS-{config_parameters["INVENTORY_NUMBER"]}'
logging.info(f'Determined that the Telco hostname should be: {hostname}')

try:
    ssh_command = f'ssh {secrets.telco_username}@{mgmt_ip} -oHostKeyAlgorithms=ssh-dss -oKexAlgorithms=diffie-hellman-group1-sha1 -oCiphers=3des-cbc -o StrictHostKeyChecking=no'
    logging.info(f'SSHing to Telco with command: {ssh_command}')
    child = pexpect.spawn(ssh_command)
    child.expect('password:', 10)
    logging.info(f'SSH succeeded, got password prompt.')

except:
    print(f'Could not SSH to the Telco at {mgmt_ip}. Exiting script.')
    logging.critical(f'Could not SSH to the Telco at {mgmt_ip}. Exiting script.')
    sys.exit(1)

try:
    logging.info(f'Entering password...')
    child.sendline(secrets.telco_password)
    child.expect(f'{hostname}>', 10)
    logging.info(f'Login success. Output after entering password: {child.after}')

    logging.info(f'Entering enable mode...')
    child.sendline('en')
    child.expect(f'{hostname}#', 10)
    logging.info(f'Successfully entered enable mode.')

except:
    print('The hostname does not match the inventory number, or SSH login failed. Please double check this is the correct Telco.')
    logging.critical(f'Failure: SSH login failed or hostname may not match inventory number. Exiting...')
    sys.exit(1)

#Get uplink from CAM table. It is either 1/1/1 or 1/3/1.
logging.info(f'Getting CAM table for VLAN 254...')
child.sendline('show mac-address-table vlan 254 dynamic')
child.expect(f'{hostname}#', 10)
output = child.before.decode().split()
logging.info(f'CAM table output: {output}')

if '1/1/1' in output:
    config_parameters['UPLINK'] = '1/1/1'
    print('Found uplink: 1/1/1')
    logging.info(f'Found uplink: 1/1/1')

elif '1/3/1' in output:
    config_parameters['UPLINK'] = '1/3/1'
    print('Found uplink: 1/3/1')
    logging.info(f'Found uplink: 1/3/1')

else:
    print('Uplink is not currently on 1/1/1 or 1/3/1. Please double check the current uplink of the Telco.')
    logging.critical('Could not get uplink - it is not 1/1/1 or 1/3/1. Exiting...')
    sys.exit(1)

#Generate config
logging.info('Generating config...')
config = generate_280_config(config_parameters)
logging.info(f'Generated config: {config}')

#Apply config
new_hostname = config_parameters["HOSTNAME"]
child.sendline(config)
child.expect(f'{new_hostname}#', 20)
logging.info('Successfully applied config')
#child.sendline('wr mem')
#child.expect(f'{new_hostname}#', 20)
#logging.info('Saved config to device')

#Change Mgmt IP descriptions in IPAM to <PON> -- <Company> -- <Address> format
new_ipam_description = ''
for service in config_parameters['SERVICES']:
    new_ipam_description += f'{service["PON"]} '

new_ipam_description += f'- {config_parameters["SERVICES"][0]["COMPANY_NAME"]} - {config_parameters["SERVICES"][0]["STREET"]} {config_parameters["SERVICES"][0]["CITY"]}, {config_parameters["SERVICES"][0]["STATE"]} {config_parameters["SERVICES"][0]["ZIP_CODE"]} - '

for service in config_parameters['SERVICES']:
    new_ipam_description += f'{service["TYPE"]} '

new_ipam_description = new_ipam_description.strip()
logging.info(f'New IPAM description: {new_ipam_description}')
#change_mgmt_ip_descriptions(inventory_number, new_ipam_description)

#Email engineering
send_completed_email(core_port_details['router_hostname'], core_port_details['port_name'], new_hostname)