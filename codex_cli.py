#!/usr/bin/env python

import os
import subprocess
import signal
import openai
import telnetlib
import argparse
import time
import sys
from transformers import GPT2TokenizerFast
from colorama import init
from colorama import Fore, Back, Style
init()

# Debug: print out the transcript of the conversation so far
# when Control-C is pressed
def sigint_handler(signum, frame):
    print("\n\n\n")
    print("Transcript:")
    print("==========")
    print(conversation)
    print("==========")
    print("\n\n\n")
    sys.exit(0)
signal.signal(signal.SIGINT, sigint_handler)

BASENAME = os.path.dirname(os.path.realpath(__file__))
DEFAULT_KEY_PATH = os.path.join(BASENAME, 'openai.key')
DEFAULT_QCOW = '/home/moyix/.panda/bionic-server-cloudimg-amd64-noaslr-nokaslr.qcow2'
DEFAULT_SNAPSHOT = 'bootroot'

engine_tokens = {
    'code-davinci-001': 4096,
    'code-cushman-001': 2048,
}

parser = argparse.ArgumentParser(description='Run Codex on a QEMU instance.')
parser.add_argument('-t', '--temperature', type=float, default=0.8, help='Temperature for the model.')
parser.add_argument('-f', '--frequency', type=float, default=1.0, help='Frequency penalty for the model (-2.0 - 2.0).')
parser.add_argument('-e', '--engine', type=str, default='code-davinci-001', choices=list(engine_tokens.keys()), help='Engine to use.')
parser.add_argument('-k', '--key', type=str, default=DEFAULT_KEY_PATH, help='Path to the OpenAI API key.')
parser.add_argument('-p', '--port', type=int, default=3456, help='Port to connect to.')
parser.add_argument('-w', '--whole-context', action='store_true', help='Use the whole conversation as context.')
parser.add_argument('-q', '--qcow', type=str, default=DEFAULT_QCOW, help='Path to the QEMU image.')
parser.add_argument('-s', '--snapshot', type=str, default=DEFAULT_SNAPSHOT, help='Snapshot to boot from.')
args = parser.parse_args()

openai.api_key_path = args.key

tok = GPT2TokenizerFast(os.path.join(BASENAME, 'tokenizer.json'),
                        os.path.join(BASENAME, 'vocab.bpe'))

MAX_TOKENS = engine_tokens[args.engine] - 128
TEMPERATURE = args.temperature
WHOLE_CONVERSATION = args.whole_context

QEMU_CMD = [
    'qemu-system-x86_64',
    '-m', '1G', 
    '-hda', args.qcow,
    '-machine', 'accel=kvm',
    '-serial', f'telnet:localhost:{args.port},server,nowait',
    '-display', 'none',
    '-net', 'nic', '-net', 'user', '-loadvm', args.snapshot,
]

def trim_prompt(s):
    tokens = tok.encode(s)
    while len(tokens) > MAX_TOKENS:
        s = '\n'.join(s.splitlines()[1:])
        tokens = tok.encode(s)
    return s

def get_next_response(prompt):
    # print(f"[Codex DEBUG ->] {repr(prompt)}")
    response = openai.Completion.create(
        engine="code-davinci-001",
        echo=False,
        prompt=prompt,
        temperature=TEMPERATURE,
        frequency_penalty=args.frequency,
        max_tokens=128,
        top_p=1.0,
        stop = '\n',
    )
    r = response['choices'][0]['text']
    # print(f"[Codex DEBUG <-] {repr(r)}")
    return r.rstrip()

def codex_print(s):
    sys.stdout.write(Fore.RED + s + Style.RESET_ALL)

def qemu_print(s):
    sys.stdout.write(Style.RESET_ALL + s + Style.RESET_ALL)

def write_raw_sequence(tn, seq):
    sock = tn.get_socket()
    if sock is not None:
        sock.send(seq)

unlikely = os.urandom(16)
def read_all_data(tn, resp):
    all_data = ''
    data = tn.read_until(unlikely, timeout=1).decode('utf-8',errors='ignore')
    if data.startswith(resp):
        data = data[len(resp):].lstrip()
    while data:
        qemu_print(data)
        all_data += data
        data = tn.read_until(unlikely, timeout=1).decode('utf-8',errors='ignore')
    # if not all_data:
    #     # Maybe we're stuck? Try sending control-c
    #     # tn.write(b'\x04') # control-d
    #     # time.sleep(0.1)
    #     tn.write(b'\x03') # control-c
    #     time.sleep(0.1)
    #     data = tn.read_until(unlikely, timeout=1).decode('utf-8',errors='ignore')
    #     if data:
    #         qemu_print(data)
    #         all_data += data
    return all_data

# Launch the VM
qproc = subprocess.Popen(QEMU_CMD)
# Connect to it
while True:
    try:
        tn = telnetlib.Telnet('localhost', args.port)
        break
    except:
        time.sleep(1)

# Disable echo
write_raw_sequence(tn, telnetlib.IAC + telnetlib.WILL + telnetlib.ECHO)

conversation = ''
# Hit enter
tn.write(b'\n')
qemu_print('\n')
conversation += '\n'
data = tn.read_until(unlikely, timeout=1).decode('utf-8',errors='ignore')
qemu_print(data)
conversation += data
if WHOLE_CONVERSATION:
    conversation = trim_prompt(conversation)
    resp = get_next_response(conversation)
else:
    resp = get_next_response(trim_prompt(data))
while True:
    codex_print(resp + '\n')
    tn.write(resp.encode('utf-8') + b'\n')
    conversation += resp + '\n'
    data = read_all_data(tn, resp)
    # print(f"[QEMU DEBUG] {data}")
    conversation += data
    if WHOLE_CONVERSATION:
        conversation = trim_prompt(conversation)
        resp = get_next_response(conversation)
    else:
        resp = get_next_response(trim_prompt(data))
