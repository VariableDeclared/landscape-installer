# landscape-installer
A script to handle all your landscape needs

## Setting up passwordless sudo

In order to run the script remotely, you will need to configure passwordless sudo on target machines.

To do this you will need to add the following line to the sudoers:

```
$ USER="USERNAME"
$ cat <<END > USER.sudoers

${USER} ALL=(ALL) NOPASSWD:ALL

END

Then to install the file, run: 

$ sudo install -C -m 440 -o root -g root USER.sudoers /etc/sudoers.d/${USERNAME}
```

In order to keep sudoers organised the new file should then appear in `/etc/sudoers.d/REPLACEME`.

## How to use

Firstly you will need to configure the landscape server config. By default the script will look for this config file in the working directory (.) under the name landscape-config.json.

The format of the json file is as follows:
```
{
    "account_name": "pjds",
    "landscape_server": "172.27.60.189",
    "registration_key": "test",
    "tags": ["dev", "20.04"],
    "access_group": "org"
}
```
Start with

```
sudo ./install_clients.py --help
```

To run install the clients do on a set of nodes, run the following:

```
sudo ./install_clients.py IP1,IP2,FQN1,FQDN2

```

Or to install on the machine that the script is running on use the `--localhost` argument.

```
sudo ./install_clients.py --localhost
```

