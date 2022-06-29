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
import os
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

SSH_KEY_LOCATION = f"/home/{os.getenv('SUDO_USER')}/.ssh/id_rsa"

def print_version():
    print("Landscape installer, v1.0~42b6f2a")

class LandscapeConfigEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, LandscapeConfig):
            return { 'account_name': o.account_name, 'landscape_server': o.landscape_server, 'registration_key': o.registration_key, 'tags': o.tags, 'access_group': o.access_group, 'remote_user': o.remote_user, 'script_users': o.script_users }

class LandscapeConfigDecoder(json.JSONDecoder):
    def decode(self, string):
        config_dict = json.loads(string)
        try:
            return LandscapeConfig(config_dict['account_name'], config_dict['landscape_server'], config_dict['registration_key'], config_dict['tags'], config_dict["access_group"], config_dict["remote_user"], config_dict["script_users"])
        except Exception as ex:
            print(f"Key is missing from config or invalid: {ex} This key is required. Exiting.")
            exit(1)

class VersionAction(argparse.Action):
    def __call__(self, parser, ns, values, option):
        print_version()
        exit(0)

class ToggleAction(argparse.Action):
    def __call__(self, parser, ns, values, option):
        setattr(ns, self.dest, 'no' not in option)

class LandscapeConfig(object):
    def validate_str_args(self, arg):
        if type(arg) is not str:
            raise ValueError(f"Keys should be of value string. Check the landscape config file")
        return arg
    def check_for_list(self, obj, name):
        if type(obj) is not list:
            raise ValueError(f"""{name} is a list. 
Ensure {name} element has the form:
"{name}": ["tag1", "tag2"]
""")
        if(type(obj[0]) is not str):
            raise ValueError("""Tags should take string form
Elements take the form:
"{name}": ["str1", "str2"]
""")
        return obj

    def __init__(self, *args):
        self.account_name = self.validate_str_args(args[0])
        self.landscape_server = self.validate_str_args(args[1])
        self.registration_key = self.validate_str_args(args[2])
        self.tags = self.check_for_list(args[3], "tags")
        self.access_group = self.validate_str_args(args[4])
        self.remote_user = self.validate_str_args(args[5])
        self.script_users = self.check_for_list(args[6], "script_users")



def cleanup(nodes, user, localhost):
    for node in nodes:
        ssh(node, user, "sudo apt-get purge landscape-client -y", not localhost)
        ssh(node, user, "sudo rm -rf /etc/landscape/", not localhost)
        ssh(node, user, "sudo rm -rf /var/lib/landscape", not localhost)

def call_logging_output(command_pieces):
    process = subprocess.Popen(command_pieces, stdout=subprocess.PIPE)
    for line in iter(lambda: process.stdout.readline(), b''):
        sys.stdout.write(line.decode('utf-8'))
        logger.debug(line)
    # process.terminate()

def call_without_logging(command_pieces):
    process = subprocess.Popen(command_pieces)
    # process.terminate()

def ssh(host, user, extra_commands, ssh=True, return_output=True):
    if ssh:
        command = f"ssh -i {SSH_KEY_LOCATION} {user}@{host} -o StrictHostKeyChecking=no -- ".split(" ")
        if return_output:
          call_logging_output(command + [extra_commands])
        else:
          call_without_logging(command + [extra_commands])
    else:
        if return_output:
          call_logging_output(extra_commands.split(" "))
        else:
          call_without_logging(extra_commands.split(" "))


def scp(host, user, local_location, target_location):
    command = f"scp -i {SSH_KEY_LOCATION} -o StrictHostKeyChecking=no {local_location} {user}@{host}:{target_location}".split(" ")
    call(command)

def update_permissions(node, user, folders, localhost):
    for folder in folders:
        ssh(node, user, f"sudo chown landscape:landscape {folder}", not localhost)
        ssh(node, user, f"sudo chmod ug+wrx {folder}", not localhost)

def setup_sudoers(node, user, remote_install):
    if remote_install:
        with NamedTemporaryFile() as sudoers_file:
            sudoers_file.write(bytes('landscape ALL=(ALL) NOPASSWD:ALL', 'utf-8'))
            sudoers_file.flush()
            scp(node, user, sudoers_file.name, "/tmp/sudoers_file")
        ssh(node, user, "sudo install -C -m 440 -o root -g root /tmp/sudoers_file /etc/sudoers.d/landscape", remote_install) 
    else:
        ps = subprocess.Popen(['echo', 'landscape ALL=(ALL) NOPASSWD:ALL'], stdout=subprocess.PIPE)
        output = subprocess.check_output(['tee', '/etc/sudoers.d/landscape'], stdin=ps.stdout)
        ps.wait()

# TODO: We're assuming that the user has PASSWORDLESS sudo AND
# we're also assuming that the user has passwordless SSH.
def install_landscape_client(nodes, user, localhost):
    for node in nodes:
        print(f"Installing landscape client to: {node}")
        # ensure landscape directories
        ssh(node, user, "sudo mkdir /etc/landscape", not localhost)
        ssh(node, user, "sudo apt-get install -y landscape-client", not localhost)
        ssh(node, user, "sudo mkdir /var/lib/landscape", not localhost)
        ssh(node, user, "sudo sed -iE s/RUN=0/RUN=1/g /etc/init.d/landscape-client", not localhost)
        setup_sudoers(node, user, not localhost)
        update_permissions(node, user, ['/etc/landscape', '/var/lib/landscape'], localhost)

def register_landscape_client(nodes, config, localhost):
    expression = re.compile(r' *Static hostname: {1}(?P<hostname>[a-zA-Z0-9-]*)', re.MULTILINE)
    landscape_config_contents = f"""[client]
log_level = info
url = https://{config.landscape_server}/message-system
ping_url = http://{config.landscape_server}/ping
data_path = /var/lib/landscape/client
account_name = {config.account_name}
registration_key = {config.registration_key}
access_group = {config.access_group}
tags = {','.join(config.tags)}
computer_title = %s
script_users = {','.join(config.script_users)}
include_manager_plugins = ScriptExecution
"""

    for node in nodes:
        hostname = expression.search(ssh_and_get_output(node, config.remote_user, "hostnamectl", not localhost)).group("hostname")
        with NamedTemporaryFile(delete=False) as tempfile:
            content = landscape_config_contents % hostname
            tempfile.write(bytes(content, 'utf-8'))
            tempfile.flush()
            if localhost:
                ssh(node, config.remote_user, f"cp {tempfile.name} /etc/landscape/client.conf", not localhost)
            else:         
                scp(node, config.remote_user, tempfile.name, "/tmp/client.conf")
                ssh(node, config.remote_user, f"sudo cp /tmp/client.conf /etc/landscape/client.conf", not localhost)
        # ssh(node, "sudo landscape-config --silent --ok-no-register", not localhost, False)
        ssh(node, config.remote_user, "sudo chown root:landscape /etc/landscape/client.conf", not localhost)
        ssh(node, config.remote_user, "sudo chmod ug+wrx /etc/landscape/client.conf", not localhost)
        ssh(node, config.remote_user, "sudo systemctl enable landscape-client.service", not localhost)
        ssh(node, config.remote_user, "sudo service landscape-client restart", not localhost)



def ssh_and_get_output(host, user, extra_commands, ssh=True):
    command = []
    if ssh:
        command = f"ssh -i {SSH_KEY_LOCATION} {user}@{host} -o StrictHostKeyChecking=no -- ".split(" ")
        return call(command + [extra_commands])
    else:
        return call(extra_commands.split(" "))

def call(command):
    return subprocess.check_output(command).decode('utf-8')

def check_landscape_client(nodes, user, localhost):
    node_status = {}
    expression = re.compile(r'Active: {1}(?P<status>[a-zA-Z \(\)]*) since', re.MULTILINE)
    for node in nodes:
        ssh_output = ssh_and_get_output(node, user, f"systemctl status landscape-client", not localhost)
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
parser.add_argument('--version', action=VersionAction, nargs=0, type=bool, help="Print the version of this application")
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
    'action_install_landscape_client': [validate_client_args(args.clients), landscape_config.remote_user, args.localhost],
    'action_register_landscape_client': [validate_client_args(args.clients), landscape_config, args.localhost],
    'action_check_landscape_client': [validate_client_args(args.clients), landscape_config.remote_user, args.localhost],
    'action_cleanup': [validate_client_args(args.clients), args.localhost]
}



def main():
    print_version()
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
    if os.getgid() != 0:
        print(f"Script must be run as root. please run sudo {__file__}")
        exit(1)
    main()
