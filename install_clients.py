#!/usr/bin/env python3
import argparse
import json
import logging
import pdb
import subprocess
import sys
import re 
import ipaddress
import socket
from tempfile import NamedTemporaryFile
# TODO:
# HANDLE ALL ERRORS
# Cleanup function - TEST
# 

LOGGING_FILE = "landscape-installer.log"
logging.basicConfig(filename=LOGGING_FILE, level=logging.DEBUG)
logger = logging.getLogger()
CLEINT_LIST = []

DIRECTORY_PREFIX = "."
CONFIG_DIRECTORY = f"{DIRECTORY_PREFIX}/landscape-config.json"

SSH_KEY_LOCATION = "~/.ssh/id_rsa"
class LandscapeConfigEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, LandscapeConfig):
            return { 'account_name': o.account_name, 'landscape_server': o.landscape_server, 'registration_key': o.registration_key, 'tags': o.tags }

class LandscapeConfigDecoder(json.JSONDecoder):
    def decode(self, string):
        config_dict = json.loads(string)
        try:
            return LandscapeConfig(config_dict['account_name'], config_dict['landscape_server'], config_dict['registration_key'], config_dict['tags'])
        except Exception as ex:
            print(f"Key is missing from config or invalid: {ex} This key is required. Exiting.")
            exit(1)


class ToggleAction(argparse.Action):
    def __call__(self, parser, ns, values, option):
        setattr(ns, self.dest, 'no' not in option)

class LandscapeConfig(object):
    def validate_str_args(self, arg):
        if type(arg) is not str:
            raise ValueError(f"Keys should be of value string. Check the landscape config file")
        return arg
    def __init__(self, *args):
        self.account_name = self.validate_str_args(args[0])
        self.landscape_server = self.validate_str_args(args[1])
        self.registration_key = self.validate_str_args(args[2])
        if type(args[3]) is not list:
            raise ValueError(""" Tags is a list. 
Ensure tags element has the form:
"tags": ["tag1", "tag2"]
""")
        if(type(args[3][0]) is not str):
            raise ValueError("""Tags should take string form
Elements take the form:
"tags": ["str1", "str2"]
""")
        self.tags = args[3]



def cleanup(nodes, localhost):
    for node in nodes:
        ssh(node, "sudo apt-get remove landscape-client -y", not localhost)
        ssh(node, "sudo rm /etc/landscape/client.conf", not localhost)

def call_logging_output(command_pieces):
    process = subprocess.Popen(command_pieces, stdout=subprocess.PIPE)
    for line in iter(lambda: process.stdout.readline(), b''):
        sys.stdout.write(line.decode('utf-8'))
        logger.debug(line)


def ssh(host, extra_commands, ssh=True):
    if ssh:
        command = f"ssh -i {SSH_KEY_LOCATION} ubuntu@{host} -o StrictHostKeyChecking=no -- ".split(" ")
        call_logging_output(command + [extra_commands])
    else:
        call_logging_output(extra_commands.split(" "))

def scp(host, local_location, target_location):
    command = f"scp -i {SSH_KEY_LOCATION} -o StrictHostKeyChecking=no {local_location} ubuntu@{host}:{target_location}".split(" ")
    call(command)

# TODO: We're assuming that the user has PASSWORDLESS sudo AND
# we're also assuming that the user has passwordless SSH.
def install_landscape_client(nodes, localhost):
    for node in nodes:
        print(f"Installing landscape client to: {node}")
        ssh(node,"sudo apt-get install -y landscape-client", not localhost)
        # ensure landscape directories
        ssh(node, "sudo mkdir /etc/landscape", not localhost)
        ssh(node, "sudo mkdir /etc/landscape", not localhost)

def register_landscape_client(nodes, config, localhost):
    expression = re.compile(r' *Static hostname: {1}(?P<hostname>[a-zA-Z0-9-]*)', re.MULTILINE)
    landscape_config_contents = f"""[client]
log_level = info
url = https://{config.landscape_server}/message-system
ping_url = http://{config.landscape_server}/ping
data_path = /var/lib/landscape/client
account_name = pjds
registration_key = test
tags = {','.join(config.tags)}
computer_title = %s
"""

    for node in nodes:
        hostname = expression.search(ssh_and_get_output(node, "hostnamectl", not localhost)).group("hostname")
        with NamedTemporaryFile() as tempfile:
            content = landscape_config_contents % hostname
            tempfile.write(bytes(content, 'utf-8'))
            tempfile.flush()
            if localhost:
                ssh(node, f"sudo mv {tempfile.name} /etc/landscape/client.conf", not localhost)
            else:
                scp(node, tempfile.name, "~/client.conf")
                ssh(node, "sudo mv client.conf /etc/landscape/client.conf", not localhost)
        ssh(node, "sudo systemctl enable landscape-client", not localhost)
        ssh(node, "sudo service landscape-client restart", not localhost)



def ssh_and_get_output(host, extra_commands, ssh=True):
    command = []
    if ssh:
        command = f"ssh -i {SSH_KEY_LOCATION} ubuntu@{host} -o StrictHostKeyChecking=no -- ".split(" ")
        return call(command + [extra_commands])
    else:
        return call(extra_commands.split(" "))

def call(command):
    return subprocess.check_output(command).decode('utf-8')

def check_landscape_client(nodes, localhost):
    node_status = {}
    expression = re.compile(r'Active: {1}(?P<status>[a-zA-Z \(\)]*) since', re.MULTILINE)
    for node in nodes:
        
        ssh_output = ssh_and_get_output(node, f"systemctl status landscape-client", not localhost)
        status = expression.search(ssh_output).group("status")
        node_status.update({
            node: status
        })
    
    for node,status in node_status.items():
        print(f"Node {node} landscape-client is: {status}")

ACTIONS = {
    'action_install_landscape_client': install_landscape_client,
    'action_register_landscape_client': register_landscape_client,
    'action_check_landscape_client': check_landscape_client
}
NON_DEFAULT_ACTIONS = {
    'action_cleanup': cleanup 
}

def actions_to_human_form(actions):
    return [action[action.find("_")+1:] for action in actions.keys()] 

STEPS = actions_to_human_form(ACTIONS) 
NON_DEFAULT_STEPS = actions_to_human_form(NON_DEFAULT_ACTIONS)

parser = argparse.ArgumentParser(description="Deploy Lanscape client to clients.")
parser.add_argument('--steps', default=",".join(STEPS), type=str, nargs="?", help=f"""
Specify steps to run, comma separated. Default runs all. 
Choose from:
{",".join(STEPS)}
"""
)
parser.add_argument('clients', default="", nargs="?", type=str, help="Comma separated clients to install the landscape client to. FQDN or IP accepted.")
parser.add_argument('--localhost', default=False, action=ToggleAction, nargs=0, type=bool, help="Dont accept client arguements, just install to localhost.")

args = parser.parse_args()

if not args.localhost and args.clients == "":
    parser.error("Clients arguement is required. Either specify --localhost or provide clients to install to.")

if args.localhost:
    args.clients = socket.gethostbyname('localhost')

landscape_config = {}
try:
    with open(CONFIG_DIRECTORY, 'r') as config_file:
        landscape_config = json.loads(config_file.read(), cls=LandscapeConfigDecoder)
        
except FileNotFoundError:
    print(f"Expected to find landscape configuration {CONFIG_DIRECTORY}. But did not. Does it exist? Exiting.")
    exit(1)

### VALIDATORS:
def validate_client_args(client_args):
    try:
        if client_args is None:
            raise TypeError("Clients cannot be none.")
        clients = []
        for client in client_args.split(","):
            # Host -> IP, IP->IP.
            # Raises socket.gaierror if host is not valid.
            clients.append(socket.gethostbyname(client))
    except Exception as ex:
        print(f"There's a problem with the client arguements. {ex}")
        exit(1)

    return clients



ACTIONS_TO_ARGS_MAP = {
    'action_install_landscape_client': [validate_client_args(args.clients), args.localhost],
    'action_register_landscape_client': [validate_client_args(args.clients), landscape_config, args.localhost],
    'action_check_landscape_client': [validate_client_args(args.clients), args.localhost],
    'action_cleanup': [validate_client_args(args.clients), args.localhost]
}


def main():
    if args.steps is None:
        print(f"""No steps specified.
Valid steps are:
{",".join(STEPS)}
There are also some non-default steps:
{",".join(NON_DEFAULT_STEPS)}""")
        exit(1)

    for step in args.steps.split(','):
        action_name = f'action_{step}'
        if action_name not in ACTIONS and \
                action_name not in NON_DEFAULT_ACTIONS:
            print(f"Invalid step specified, {action_name}. Run {__file__} --help for a list of valid steps.")
            exit(1)
        logger.debug(f"Running action {action_name}")
        try:
            ACTIONS[action_name](*ACTIONS_TO_ARGS_MAP.get(action_name,()))
        except KeyError:
            NON_DEFAULT_ACTIONS[action_name](*ACTIONS_TO_ARGS_MAP.get(action_name,()))

if __name__ == '__main__':
    main()
