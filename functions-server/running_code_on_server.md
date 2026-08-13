re# Instructions to run python code in the server

## Useful overview
https://www.digitalocean.com/community/tutorials/how-to-install-python-3-and-set-up-a-programming-environment-on-an-ubuntu-20-04-server

https://www.digitalocean.com/community/tutorials/run-python-script-on-ubuntu

-- tried running jupyter but did not work, lack of permissions in the server. Here are instructions anyway...
https://www.digitalocean.com/community/tutorials/how-to-install-run-connect-to-jupyter-notebook-on-remote-server

## Getting to the python folder

CID@cirrus:~$ cd /
CID@cirrus:/$ cd database/python
CID@cirrus:/database/python$ ls
source  venv

## Python environment
We have a general python 3 virtual environment installed under 'database/python/venv'

Source files can be copied to the 'database/python/source' folder

The environment is activated as
$ source venv/bin/activate
(venv) CID@cirrus:/database/python$

To leave the venv simply use
$ deactivate

## Installing packages
Pip commands can be run to install new packages using:

$ sudo venv/bin/pip install package

## Creating a virtual environment
For specific projects it's probably best to create a specific virtual environment (with project name)

In the python folder, simply run 
$ python3 -m venv my_env

Then activate the new environment and install required packages.

## Running code
Once the environment is active, and has all the necessary packages, Python files can be run using:

from the python folder
$ python source/my_code.py

from the source folder
$ python my_code.py



