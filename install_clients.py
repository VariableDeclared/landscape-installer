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

#TODO:
# Localhost install
# HANDLE ALL ERRORS

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
            return { 'account-name': o.account_name, 'landscape-server': o.landscape_server, 'registration-key': o.registration_key, 'tags': o.tags }

class ToggleAction(argparse.Action):
    def __call__(self, parser, ns, values, option):
        setattr(ns, self.dest, 'no' not in option)

class LandscapeConfig(object):
    def __init__(self, *args):
        self.account_name = args[0]
        self.landscape_server = args[1]
        self.registration_key = args[2]
        self.tags = args[3]

    def decode_config(config_line):
        config = json.loads(config_line)
        return LandscapeConfig(config['account-name'], config['landscape-server'], config['registration-key'], config['tags'])


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

# TODO: We're assuming that the user has PASSWORDLESS sudo AND
# we're also assuming that the user has passwordless SSH.
def install_landscape_client(nodes, localhost):
    for node in nodes:
        print(f"Installing landscape client to: {node}")
        ssh(node,"sudo apt-get install -y landscape-client", not localhost)


def register_landscape_client(nodes, config, localhost):
    for node in nodes:
        ssh(node, f"sudo landscape-config --silent --account-name {config.account_name} \
                --url https://{config.landscape_server}/message-system \
                --ping-url http://{config.landscape_server}/ping \
                -p {config.registration_key} \
                --tags {','.join(config.tags)}" \
                " -t $(hostnamectl | grep 'Static hostname:' | awk '{print $3}')", not localhost)


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
        # pdb.set_trace()
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


STEPS = [action[action.find("_")+1:] for action in ACTIONS.keys()] 
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
        landscape_config = LandscapeConfig.decode_config(config_file.read())
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
    'action_check_landscape_client': [validate_client_args(args.clients), args.localhost]
}


def main():
    for step in args.steps.split(','):
        action_name = f'action_{step}'
        logger.debug(f"Running action {action_name}")
        # pdb.set_trace()
        ACTIONS[action_name](*ACTIONS_TO_ARGS_MAP.get(action_name,()))

if __name__ == '__main__':
    main()
