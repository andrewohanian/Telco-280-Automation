import json
import requests
import urllib3
import ipaddress
import sys
import secrets
import logging
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def get_ipam_token():
    """
    Gets the phpIPAM API token using the Base64 encoded user/pass from the secrets.py file.
    """
    url = f"{secrets.ipam_base_url}/api/python/user"

    headers = {'Authorization': secrets.ipam_authentication}

    response = requests.request("POST", url, headers=headers, verify=False)

    return response.json()['data']['token']


def get_mgmt_subnet_id(token):
    """
    Gets the Mgmt subnet ID from the Private Nets (3) section.
    """
    url = f"{secrets.ipam_base_url}/api/python/sections/3/subnets"

    headers = {'token': token}

    response = requests.request("GET", url, headers=headers, verify=False)

    for subnet in response.json()['data']:
        if subnet['subnet'] == '10.254.0.0':
            logging.info(f'Mgmt 10.254/16 subnet ID is {subnet["subnet"]}')
            return subnet['id']


def get_all_mgmt_addresses(token, mgmt_subnet_id):
    """
    Returns a list of every IP address from the Mgmt 10.254/16 subnet.
    """
    url = f"{secrets.ipam_base_url}/api/python/subnets/{mgmt_subnet_id}/addresses"

    headers = {'token': token}

    response = requests.request("GET", url, headers=headers, verify=False)

    all_ip_addresses = []
    for address in response.json()['data']:
        all_ip_addresses.append(address['ip'])

    return all_ip_addresses


def get_first_available_mgmt_ip(token, mgmt_subnet_id):
    """
    Gets the first available Mgmt IP, ensures that it is the base of a /30 subnet, 
    and ensures that the next 3 consecutive IPs are available.
    If these checks pass, it returns the subnet IP (which is the first available IP).
    """
    url = f"{secrets.ipam_base_url}/api/python/subnets/{mgmt_subnet_id}/first_free"

    headers = {'token': token}

    response = requests.request("GET", url, headers=headers, verify=False)

    first_available_ip = ipaddress.ip_address(response.json()['data'])
    logging.info(f'First available 10.254/16 IP is {first_available_ip}')

    #Check that the first available IP is the base of a /30 subnet
    last_octect = int(str(first_available_ip).split('.')[-1])
    if last_octect % 4 != 0:
        print(f'The first available mgmt IP, {str(first_available_ip)} is not the first IP of a /30 subnet.')
        print('Please make sure that the first available mgmt IP in 10.254.0.0/19 is the base of a /30 subnet and then retry the script.')
        logging.critical(f'The first available mgmt IP, {str(first_available_ip)} is not the first IP of a /30 subnet.')
        sys.exit(1)

    #Check that the next 3 IPs in the /30 are not already reserved
    all_ip_addresses = get_all_mgmt_addresses(token, mgmt_subnet_id)
    for i in range(1,4):
        if str(first_available_ip + i) in all_ip_addresses:
            print('The first available mgmt IP does not have the next 3 consecutive IPs available.')
            print(f'Please verify that {str(first_available_ip)} through {str(first_available_ip + 3)} is available in IPAM.')
            logging.critical(f'The first available mgmt IP, {str(first_available_ip)} is not the first IP of a /30 subnet.')
            sys.exit(1)
    
    return first_available_ip


def reserve_ip_address(mgmt_subnet_id, ip_description, token):
    """
    Reserves the next available IP address in the 10.254./16 subnet.
    """
    url = f"{secrets.ipam_base_url}/api/python/addresses/first_free/{mgmt_subnet_id}"

    headers = {
    'token': token,
    'Content-Type': 'application/json'
    }

    payload = {
        "hostname" : ip_description,
        "description": ''
    }

    response = requests.request("POST", url, headers=headers, json=payload, verify=False)

    if response.status_code == 201:
        print(f"Reserved IP: {response.json()['data']}  Description: {ip_description}")
    
    else:
        print(f'Error reserving the mgmt IP, status code {response.status_code}. Please double check the first available Mgmt IP in IPAM.')
        sys.exit(1)


def get_mgmt_ip_and_reserve_in_ipam(ipam_description):
    """
    Obtains the first available 10.254/16 Mgmt IP, then reserves the 4 IPs in the /30
    by reserving the first available IP four times consecutively. The IPs are reserved
    with the given ipam_description as the hostname.
    """
    token = get_ipam_token()
    mgmt_subnet_id = get_mgmt_subnet_id(token)
    mgmt_subnet_address = get_first_available_mgmt_ip(token, mgmt_subnet_id)

    for i in range(0,4):
        reserve_ip_address(mgmt_subnet_id, ipam_description, token)

    return mgmt_subnet_address


def get_mgmt_ip_from_inventory_number(inventory_number):
    """
    Given an inventory number, searches for IPs that match the string 'Telco Inventory TAG <inventory_number>'
    Four IPs should be found. The 3rd one, which is the Telco Mgmt IP (the higher host IP in the /30) is returned.
    """
    token = get_ipam_token()

    url = f"{secrets.ipam_base_url}/api/python/addresses/search_hostname/Telco Inventory TAG {inventory_number}"

    headers = {'token': token}

    response = requests.request("GET", url, headers=headers, verify=False)

    try:
        for ip_object in response.json()['data']:
            #The last octect should have a remainder of 2 when divided by 4. This is the highest usable IP in the /30.
            if int(ip_object['ip'].split('.')[-1]) % 4 == 2:
                return ip_object['ip']

    except:
        print('No address found in IPAM for given inventory number.')
        logging.critical('No address found in IPAM for given inventory number. Exiting script.')
        sys.exit(1)
        return None


def change_mgmt_ip_descriptions(inventory_number, new_description):
    """
    Changes the description (host name) of all IPs in IPAM that match a given inventory_number to the new_description.
    """
    token = get_ipam_token()

    url = f"{secrets.ipam_base_url}/api/python/addresses/search_hostname/Telco Inventory TAG {inventory_number}"

    headers = {'token': token}

    response = requests.request("GET", url, headers=headers, verify=False)
    logging.info(f'Found the following IPs matching the inventory number: {response.json()["data"]}')

    for address in response.json()['data']:
        url = f"{secrets.ipam_base_url}/api/python/addresses/{address['id']}"

        payload = {
        "hostname" : new_description,
        "description": ''
        }

        response = requests.request("PATCH", url, headers=headers, json=payload, verify=False)

        if response.status_code != 200:
            print('There was some error trying to change the IP description in IPAM.')
            logging.critical('Could not update IP description for {}. Status code was {response.status_code}. Exiting...')
            sys.exit(1)

        else:
            logging.info(f'Successfully updated description in IPAM for {address["id"]}')