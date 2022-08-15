import paramiko
import json
import requests
import secrets
import re

def get_all_interfaces_from_corenms_matching_string(search_string):
    """
    Takes a string, and searches LibreNMS for ports with an interface description matching that string.
    Returns a list of the ports that were matched.
    If there are no ports found, returns None.
    """
    url = f"{secrets.nms_base_url}/api/v0/ports/search/ifalias/{search_string}"
    headers = {'X-Auth-Token': secrets.nms_auth_token}

    response = requests.request("GET", url, headers=headers)

    try:
        return response.json()['ports']
    except:
        return None


def get_new_port_description(port_description):
    if 'MGMT' in port_description:
        new_description = re.findall('.*MGMT', port_description)[0]
    else:
        new_description = re.findall('\d+\.\d+\.\d+\.\d+', port_description)[0]

    return new_description


def get_intermediate_port_description(port_description):
    new_description = re.findall('.*\d+\.\d+\.\d+\.\d+', port_description)[0]

    return new_description


def get_port_details(port_id):
    """
    Takes a port_id and finds various details of the port by querying LibreNMS.
    First finds the interface description, ifName (i.e. Gi0/0/0/1.254) and router device ID
    Then finds the router's mgmt IP, SNMP location, hostname, and os (iosxr or iosxe)
    This is returned as a dict.
    """
    url = f"{secrets.nms_base_url}/api/v0/ports/{port_id}"
    headers = {'X-Auth-Token': secrets.nms_auth_token}
    response = requests.request("GET", url, headers=headers)

    #Populate port variables
    port_description = response.json()['port'][0]['ifAlias']
    port_name = response.json()['port'][0]['ifName']
    router_device_id = response.json()['port'][0]['device_id']

    url = f"{secrets.nms_base_url}/api/v0/devices/{router_device_id}"
    response = requests.request("GET", url, headers=headers)

    #Populate the router variables for the given port
    router_mgmt_ip = response.json()['devices'][0]['ip']
    router_location = response.json()['devices'][0]['location']
    router_hostname = response.json()['devices'][0]['hostname']
    router_os = response.json()['devices'][0]['os']

    #Return a dict of data which is needed to SSH to the router and configure the port
    return {
        'port_description' : port_description,
        'port_name' : port_name,
        'router_mgmt_ip' : router_mgmt_ip,
        'router_location' : router_location,
        'router_hostname' : router_hostname,
        'router_os' : router_os
    }


def find_prestaged_port_from_pon(list_of_pons):
    """
    Takes a list of PONs, and finds an interface which has both the string 'PRESTAGE' and
    the string <PON> in the interface description. 
    The first found port is returned, as there should only ever be a single match.
    If no ports are found, returns None.
    """
    all_prestage_ports = get_all_interfaces_from_corenms_matching_string('PRESTAGE')

    if all_prestage_ports != None:
        for prestage_port in all_prestage_ports:
            port_details = get_port_details(prestage_port['port_id'])
            for pon in list_of_pons:
                if pon in port_details['port_description']:
                    print(f'Found port {port_details["port_name"]} on {port_details["router_hostname"]} with description: {port_details["port_description"]}\n')
                    port_details['pon'] = pon
                    port_details['configured'] = False
                    return port_details

    #If there are no PRESTAGE ports at all, or there are no PRESTAGE ports which match any PON in the 
    # list of PONs, return None
    return None


def find_configured_port_from_pon(list_of_pons):
    """
    Takes a list of PONs, and finds the first interface in LibreNMS that has a PON from the list in the interface description.
    There should only ever be a single match, so the first match is returned.
    This is used when a router port has been previously configured. In this case, the string 'PRESTAGED' has been removed,
    leaving only the PON left on the interface description.
    """
    for pon in list_of_pons:
        port = get_all_interfaces_from_corenms_matching_string(pon)
        if port != None:
            port_details = get_port_details(port[0]['port_id'])
            port_details['configured'] = True
            return port_details

    return None


def find_core_port_from_pon(config_parameters):
    """
    Takes the config parameters, iterates over the services, and generate a lists of PONs that will be configured on 
    the Telco.
    From this list of PONs, finds the router port by searching for an interface with the description 
    '<PON> (PRESTAGED)' or just '<PON>'
    """
    list_of_pons = []
    for service in config_parameters['SERVICES']:
        list_of_pons.append(service['PON'])

    port_details = find_prestaged_port_from_pon(list_of_pons)

    if port_details != None:
        return port_details

    #The port may already be configured from a previous run, and did not show up as PRESTAGED
    # Search for port using just the PON, without (PRESTAGED)
    else:    
        port_details = find_configured_port_from_pon(list_of_pons)
        return port_details


def configure_router(router_mgmt_ip, router_os, port_name, intermediate_description, router_hostname, mgmt_default_gateway_ip):
    """
    Configures the router port with the correct Mgmt default GW /30 IP address, changes the port description from
    <PON> (PRESTAGED) to just <PON>, and saves the config (commit or wr mem).
    """
    router = {
        "host": router_mgmt_ip,
        "auth_username": secrets.router_username,
        "auth_password": secrets.router_password,
        "auth_strict_key": False
    }

    if router_os == 'iosxe':
        from scrapli.driver.core import IOSXEDriver
        ssh_connection = IOSXEDriver(**router)

    if router_os == 'iosxr':
        from scrapli.driver.core import IOSXRDriver
        ssh_connection = IOSXRDriver(**router)

    ssh_connection.open()
    ssh_connection.send_command("conf t")
    ssh_connection.send_command(f"interface {port_name}")
    ssh_connection.send_command(f"ip address {mgmt_default_gateway_ip} 255.255.255.252")
    ssh_connection.send_command(f"description {intermediate_description}")
    ssh_connection.send_command(f"no shut")

    if router_os == 'iosxe':
        ssh_connection.send_command('end')
        ssh_connection.send_command('write mem')

    if router_os == 'iosxr':
        ssh_connection.send_command('commit')
        ssh_connection.send_command('end')
    
    response = ssh_connection.send_command(f"show run int {port_name}")

    print(f"Configured interface {port_name} on {router_hostname}")
    print(response.result + '\n')


def configure_core_interface_description_and_show_run_interface(router_mgmt_ip, router_os, port_name, new_description):
    """
    Does show run of the interface
    """
    router = {
        "host": router_mgmt_ip,
        "auth_username": secrets.router_username,
        "auth_password": secrets.router_password,
        "auth_strict_key": False
    }

    if router_os == 'iosxe':
        from scrapli.driver.core import IOSXEDriver
        ssh_connection = IOSXEDriver(**router)

    if router_os == 'iosxr':
        from scrapli.driver.core import IOSXRDriver
        ssh_connection = IOSXRDriver(**router)

    ssh_connection.open()
    ssh_connection.send_command("conf t")
    ssh_connection.send_command(f"interface {port_name}")
    ssh_connection.send_command(f"description {new_description}")

    if router_os == 'iosxe':
        ssh_connection.send_command('end')
        ssh_connection.send_command('write mem')

    if router_os == 'iosxr':
        ssh_connection.send_command('commit')
        ssh_connection.send_command('end')
    
    response = ssh_connection.send_command(f"show run int {port_name}")
    
    show_run_output = response.result

    show_run_output = re.findall('int.*\n.*description.*', show_run_output)[0]
    
    return show_run_output