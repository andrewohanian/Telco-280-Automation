from jinja2 import Template
import sys
import logging

def generate_280_config(config_parameters):
    """
    Takes the config parameters for the Telco 280, and generates a config for the services. The base config 
    with SNMP, AAA, banner, etc, is already there from being inventoried. This only configures the interfaces,
    VLANs, TLS and SNMP location. The SNMP location was found by obtaining the router's SNMP location.
    """
    service_type_to_vlan_id = {
        'DIA': '10',
        'MPLS_PASSTHROUGH': '20',
        'SIP': '30',
        'EPL': '40',
        'EVPL': '40',
        'VPLS': '40'
    }

    #Initiliaze list of unused interfaces with all interfaces on the Telco 280
    unused_interfaces = ['1/1/1', '1/2/1', '1/2/2', '1/3/1']

    unused_interfaces.remove(config_parameters['UPLINK'])

    all_upload_bandwidth_values = []
    for service in config_parameters['SERVICES']:
        #Check to make sure the LAN interface is not the current uplink
        if service['LAN_INTERFACE'] == config_parameters['UPLINK']:
            print(f'The {service["TYPE"]} service has a LAN interface which is the current uplink of the Telco. Please correct this and try again.')
            sys.exit(1)

        if 'BANDWIDTH' in service.keys():
            service['DOWNLOAD_BANDWIDTH'] = service['BANDWIDTH']
            service['UPLOAD_BANDWIDTH'] = service['BANDWIDTH']

        all_upload_bandwidth_values.append(int(service['UPLOAD_BANDWIDTH']))

        service['VLAN'] = service_type_to_vlan_id[service['TYPE']]
        unused_interfaces.remove(service['LAN_INTERFACE'])

    config_parameters['UNUSED_INTERFACES'] = unused_interfaces
    logging.info(f'Unused interfaces which will be shutdown: {unused_interfaces}')

    #Determine whether shaper goes on uplink
    #With only one service, put the shaper on the uplink to avoid policing customer traffic. (Shape both up/down)
    if len(config_parameters['SERVICES']) == 1:
        config_parameters['SHAPER_ON_UPLINK'] = 'true'
    
    #With two services and one being SIP, also put the shaper on the uplink and the SIP upload will be shaped higher than necessary
    elif len(config_parameters['SERVICES']) == 2 and (config_parameters['SERVICES'][0]['TYPE'] == 'SIP' or config_parameters['SERVICES'][1]['TYPE'] == 'SIP'):
        config_parameters['SHAPER_ON_UPLINK'] = 'true'
    
    #With more than two services with one not being SIP, we will have to policing inbound traffic on the customer ports.
    else:
        config_parameters['SHAPER_ON_UPLINK'] = 'false'

    #Determine max bandwidth which will be used on the uplink shaper
    config_parameters['MAX_UPLOAD_BANDWIDTH'] = max(all_upload_bandwidth_values)

    #Open j2 template
    with open('files/TELCO280.j2', 'r') as telco280_template:
        telco280_template = Template(telco280_template.read())

    #Render j2 template with the config parameters
    logging.info(f'Config parameters prior to rendering template: {config_parameters}')
    telco280_config = telco280_template.render(config_parameters)
    
    #Return the config with no blank lines
    telco280_config_lines = telco280_config.split('\n')
    telco280_config_no_blank_lines = [line for line in telco280_config_lines if line.strip() != '']
    return '\n'.join(telco280_config_no_blank_lines)
    