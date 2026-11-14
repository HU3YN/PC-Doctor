"""Receiver for the PC Doctor case-sensor node. Standard library only.

packet.py     the 22-byte UDP packet: encode, decode, CRC-16
tracker.py    sequence numbers: loss, duplicates, reordering, wrap, reboots
receiver.py   UDP listener, CSV writer and the end-of-run summary
simulate.py   a pretend node for testing without hardware
__main__.py   the command line (python -m case_sensor --help)
"""
